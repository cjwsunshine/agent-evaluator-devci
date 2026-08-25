"""
TruLens provider 包装：把火山方舟（Ark）当 LLM-as-a-judge，提供给 trulens.providers.openai.OpenAI。

trulens-providers-openai 期望调用 OpenAI 兼容接口。Ark 的 /api/coding/v3 完全兼容，
所以只需要把 base_url / api_key / model_engine 透传给 TruOpenAI 即可。
"""
import os
from typing import Optional

from app.config.config import Config


_provider_singleton = None
_patches_applied = False


def get_trulens_provider():
    """获取（懒加载）单例 TruLens OpenAI Provider，已绑定到火山方舟。"""
    global _provider_singleton
    if _provider_singleton is None:
        _apply_robustness_patches()
        _provider_singleton = _build_provider()
    return _provider_singleton


def _apply_robustness_patches():
    """给 trulens 的 ChainOfThoughtResponse 加文本兜底解析。

    某些模型（含 Ark 上的 kimi/deepseek）在 with_cot_reasons 调用里偶尔会返回 Markdown 风格
    'Criteria: ...\nSupporting Evidence: ...\nScore: 3' 而非 JSON。trulens 默认严格要 JSON，
    解析失败就 retry 直到耗尽抛异常。这里在解析失败时退化到正则抽取，避免整条评测因格式波动而崩。
    """
    global _patches_applied
    if _patches_applied:
        return

    from trulens.feedback import output_schemas
    import re

    cot_cls = output_schemas.ChainOfThoughtResponse
    original_validate_json = cot_cls.model_validate_json

    @classmethod
    def patched_validate_json(cls, raw, *args, **kwargs):
        text = raw if isinstance(raw, str) else (raw.decode('utf-8', errors='replace') if isinstance(raw, (bytes, bytearray)) else str(raw))

        # 第一道：直接解析
        try:
            return original_validate_json.__func__(cls, raw, *args, **kwargs)
        except Exception:
            pass

        # 第二道：剥 Markdown code fence（```json {...} ``` / ``` {...} ```）后再解析
        fenced = re.sub(r'^\s*```(?:json)?\s*|\s*```\s*$', '', text.strip(), flags=re.IGNORECASE)
        if fenced != text.strip():
            try:
                return original_validate_json.__func__(cls, fenced, *args, **kwargs)
            except Exception:
                pass

        # 第三道：抽出第一个 {...} JSON 片段
        json_match = re.search(r'\{.*\}', text, re.DOTALL)
        if json_match:
            try:
                return original_validate_json.__func__(cls, json_match.group(0), *args, **kwargs)
            except Exception:
                pass

        # 第四道：从 "Criteria: ... Score: N" 文本里抠字段
        crit_match = re.search(r'criteria\s*:\s*(.*?)(?:\n\n|\n(?=supporting|score)|$)', text, re.IGNORECASE | re.DOTALL)
        evid_match = re.search(r'supporting\s*evidence\s*:\s*(.*?)(?:\n\n|\n(?=score)|$)', text, re.IGNORECASE | re.DOTALL)
        score_match = re.search(r'score\s*[:=]?\s*(-?\d+(?:\.\d+)?)', text, re.IGNORECASE)
        if score_match:
            try:
                score = int(round(float(score_match.group(1))))
            except (TypeError, ValueError):
                score = 0
            return cls(
                criteria=(crit_match.group(1).strip() if crit_match else 'parsed from text fallback')[:1000],
                supporting_evidence=(evid_match.group(1).strip() if evid_match else text[:500]),
                score=score,
            )
        # 都失败就抛回原异常（让 trulens retry / 标失败）
        return original_validate_json.__func__(cls, raw, *args, **kwargs)

    cot_cls.model_validate_json = patched_validate_json
    _patches_applied = True


def _build_provider():
    # 懒导入避免应用启动时强依赖 trulens
    from trulens.providers.openai import OpenAI as TruOpenAI

    runtime = Config.get_runtime_config()
    api_key = runtime.get('ark_api_key') or os.environ.get('ARK_API_KEY', '')
    base_url = runtime.get('ark_base_url') or os.environ.get('ARK_BASE_URL', '')
    model_name = runtime.get('evaluation_model') or runtime.get('execution_model') or 'deepseek-v3.2'

    if not api_key:
        raise RuntimeError(
            '未配置 ARK_API_KEY，无法启用 TruLens 真实评测。请在 .env 或系统设置中设置。'
        )

    # trulens 内部某些代码路径会直接读 OPENAI_API_KEY/OPENAI_BASE_URL，确保都走 Ark
    os.environ['OPENAI_API_KEY'] = api_key
    if base_url:
        os.environ['OPENAI_BASE_URL'] = base_url

    return TruOpenAI(
        model_engine=model_name,
        api_key=api_key,
        base_url=base_url,
    )


def call_feedback(metric_name: str, *, query: str, agent_output: str, expected: str,
                  input_payload=None, expected_payload=None, agent_output_payload=None):
    """根据业务 metric 名调对应 trulens feedback 函数。

    返回 (score_0_to_1: float, reason_text: str|None, used_metric: str, context_info: dict)；
    任一异常都被吞掉转为 (None, 错误描述, used_metric, 诊断信息)，交给上层 evaluator 决定怎么处理。

    若传入的 metric 不属于 trulens 三件套（answer_relevance / context_relevance / groundedness），
    则回退到 answer_relevance（最通用），used_metric 会标注真实使用的指标，便于在日志里追溯。

    结构化 payload 优先用于：
      - groundedness: 从 input_payload.context 取真实检索结果（替代 expected 字符串）
      - context_relevance: 同上，用真实检索上下文，不用 expected 凑数
    """
    provider = get_trulens_provider()
    name = (metric_name or '').strip()
    if name not in {'answer_relevance', 'context_relevance', 'groundedness'}:
        used_metric = 'answer_relevance'
    else:
        used_metric = name

    # 从 payload 取真实检索上下文。注意 groundedness 强依赖"真实上下文/来源文本"——
    # 我们只在 answer_relevance / context_relevance 场景才允许把 expected 当兜底，
    # 因为 groundedness 拿 expected（往往是一句评分标准）去做证据比对会得到荒谬的 0 分，
    # 反而误导用户。真实缺 context 时，直接返回错误提示更诚实。
    retrieval_context = None
    if input_payload and isinstance(input_payload, dict) and input_payload.get('context'):
        retrieval_context = str(input_payload['context'])
    elif expected_payload and isinstance(expected_payload, dict) and expected_payload.get('context'):
        retrieval_context = str(expected_payload['context'])
    elif expected and used_metric != 'groundedness':
        retrieval_context = expected

    context_info = {
        'used_real_retrieval_context': retrieval_context is not None and retrieval_context != expected,
        'source_payload': 'input_payload' if (input_payload and input_payload.get('context')) else 'expected_payload' if (expected_payload and expected_payload.get('context')) else None,
    }

    if used_metric == 'groundedness' and not retrieval_context:
        return None, (
            'groundedness 需要真实的检索/工具上下文来作为"来源"。'
            '请在用例的 input_payload.context（或 expected_payload.context）中填入 agent 检索到的原始文本，'
            '例如工具返回的天气 JSON、检索到的原文段落等。'
            '若只想评估"回答是否切题"，请改用 answer_relevance 指标；'
            '若想按一段自然语言标准评分，请改用 deepeval 的 geval 或 promptfoo 的 red_team_pass_rate（llm-rubric）。'
        ), used_metric, context_info

    try:
        if used_metric == 'answer_relevance':
            score, reason_dict = provider.relevance_with_cot_reasons(query or '', agent_output or '')
            return float(score), _flatten_reason(reason_dict), used_metric, context_info

        if used_metric == 'context_relevance':
            context = retrieval_context or agent_output or ''
            score, reason_dict = provider.context_relevance_with_cot_reasons(query or '', context)
            return float(score), _flatten_reason(reason_dict), used_metric, context_info

        if used_metric == 'groundedness':
            from trulens.core.metric.metric import GroundednessConfigs
            cfg = GroundednessConfigs(use_sent_tokenize=False, filter_trivial_statements=False)
            source = retrieval_context or query or ''
            score, reason_dict = provider.groundedness_measure_with_cot_reasons(
                source, agent_output or '', groundedness_configs=cfg
            )
            return float(score), _flatten_reason(reason_dict), used_metric, context_info
    except Exception as exc:  # noqa: BLE001
        return None, f'TruLens 内部异常: {exc}', used_metric, context_info

    return None, f'未知的 trulens metric: {name}', used_metric, context_info


def _flatten_reason(reason_dict) -> Optional[str]:
    if not reason_dict:
        return None
    if isinstance(reason_dict, str):
        return reason_dict
    if isinstance(reason_dict, dict):
        # trulens 一般返回 {'reason': '...'}，少数返回多键
        return '\n\n'.join(f'{k}: {v}' for k, v in reason_dict.items())
    return str(reason_dict)

