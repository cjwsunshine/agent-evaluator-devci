"""RAGAS provider wrapper for Ark/OpenAI-compatible evaluation.

The RAGAS public API has changed across versions. This module keeps those
version-specific details away from the main evaluation engine and returns a
small stable tuple to callers.
"""
import asyncio
import concurrent.futures
import math
import os
import time
from typing import Any, Dict, List, Optional, Tuple

from app.config.config import Config


METRIC_NAMES = {
    'answer_correctness': ['answer_correctness', 'AnswerCorrectness'],
    'answer_relevancy': ['answer_relevancy', 'AnswerRelevancy', 'ResponseRelevancy'],
    'faithfulness': ['faithfulness', 'Faithfulness'],
    'context_precision': ['context_precision', 'ContextPrecision', 'LLMContextPrecisionWithReference'],
    'context_recall': ['context_recall', 'ContextRecall', 'LLMContextRecall'],
    'context_entity_recall': ['context_entity_recall', 'ContextEntityRecall'],
    'noise_sensitivity': ['noise_sensitivity', 'NoiseSensitivity'],
}

REQUIRED_FIELDS = {
    'answer_correctness': ['reference'],
    'answer_relevancy': [],
    'faithfulness': ['contexts'],
    'context_precision': ['contexts', 'reference'],
    'context_recall': ['contexts', 'reference'],
    'context_entity_recall': ['contexts', 'reference'],
    'noise_sensitivity': ['contexts', 'reference'],
}

FALLBACK_METRICS = {
    'context_entity_recall': 'context_recall',
    'noise_sensitivity': 'faithfulness',
}

DEFAULT_TIMEOUT_SECONDS = 90


class RagasInputError(ValueError):
    """Raised when a RAGAS metric cannot run because required fields are absent."""


class ArkOpenAIRagasLLM:
    """Minimal RAGAS LLM wrapper backed by the OpenAI client.

    This mirrors the Coding Plan integration style: construct an OpenAI client
    with the configured base_url, then expose the BaseRagasLLM methods RAGAS
    expects. It avoids LangChain ChatOpenAI's endpoint assumptions.
    """

    def __init__(self, *, api_key: str, base_url: str, model: str):
        from openai import OpenAI
        from ragas.llms.base import BaseRagasLLM

        class _OpenAIRagasLLM(BaseRagasLLM):
            def __init__(self, client, model_name):
                super().__init__()
                self.client = client
                self.model_name = model_name

            def generate_text(self, prompt, n=1, temperature=1e-8, stop=None, callbacks=None):
                from langchain_core.outputs import Generation, LLMResult
                text_prompt = prompt.to_string() if hasattr(prompt, 'to_string') else str(prompt)
                generations = []
                for _ in range(n):
                    response = self.client.chat.completions.create(
                        model=self.model_name,
                        messages=[{'role': 'user', 'content': text_prompt}],
                        temperature=temperature,
                        stop=stop,
                    )
                    text = response.choices[0].message.content or ''
                    finish_reason = getattr(response.choices[0], 'finish_reason', None)
                    generations.append([Generation(text=text, generation_info={'finish_reason': finish_reason or 'stop'})])
                return LLMResult(generations=generations)

            async def agenerate_text(self, prompt, n=1, temperature=None, stop=None, callbacks=None):
                return await asyncio.to_thread(
                    self.generate_text,
                    prompt,
                    n,
                    temperature if temperature is not None else 1e-8,
                    stop,
                    callbacks,
                )

        self._wrapped = _OpenAIRagasLLM(OpenAI(api_key=api_key, base_url=base_url), model)

    def as_ragas_llm(self):
        return self._wrapped

    def __getattr__(self, name):
        return getattr(self._wrapped, name)


def score_ragas_metric(metric_name: str, *, query: str, agent_output: str, expected: str,
                       input_payload=None, expected_payload=None, agent_output_payload=None):
    """Score one RAGAS metric.

    Returns (raw_score, reason, used_metric, context_info). raw_score is usually
    in [0, 1]. On recoverable errors raw_score is None and reason is actionable.
    """
    requested_metric = (metric_name or 'answer_relevancy').strip()
    if requested_metric not in METRIC_NAMES:
        requested_metric = 'answer_relevancy'

    context_info = _build_ragas_inputs(
        query=query,
        agent_output=agent_output,
        expected=expected,
        input_payload=input_payload,
        expected_payload=expected_payload,
        agent_output_payload=agent_output_payload,
    )
    context_info['requested_metric'] = metric_name

    used_metric = requested_metric
    started_at = time.monotonic()
    timeout_seconds = _get_timeout_seconds()
    context_info['timeout_seconds'] = timeout_seconds
    context_info['stage'] = 'validating_inputs'
    try:
        _validate_required_fields(used_metric, context_info)
        context_info['stage'] = 'running_ragas_metric'
        raw_score = _run_with_timeout(used_metric, context_info, timeout_seconds)
        context_info['elapsed_seconds'] = round(time.monotonic() - started_at, 2)
        context_info['stage'] = 'completed'
        return raw_score, None, used_metric, context_info
    except ImportError as exc:
        return None, f'RAGAS 依赖未安装或不完整，请运行 pip install -r requirements.txt。原始错误: {exc}', used_metric, context_info
    except RagasInputError as exc:
        return None, str(exc), used_metric, context_info
    except Exception as exc:  # noqa: BLE001
        fallback_metric = FALLBACK_METRICS.get(used_metric)
        if fallback_metric:
            try:
                _validate_required_fields(fallback_metric, context_info)
                context_info['stage'] = 'running_fallback_metric'
                raw_score = _run_with_timeout(fallback_metric, context_info, timeout_seconds)
                context_info['ragas_used_fallback'] = True
                context_info['ragas_fallback_reason'] = str(exc)
                context_info['elapsed_seconds'] = round(time.monotonic() - started_at, 2)
                context_info['stage'] = 'completed_with_fallback'
                return raw_score, f'当前 RAGAS 指标 {used_metric} 不可用，已降级为 {fallback_metric}: {exc}', fallback_metric, context_info
            except Exception as fallback_exc:  # noqa: BLE001
                return None, f'RAGAS 评测异常: {exc}; 降级 {fallback_metric} 也失败: {fallback_exc}', used_metric, context_info
        context_info['elapsed_seconds'] = round(time.monotonic() - started_at, 2)
        context_info['stage'] = 'failed'
        return None, f'RAGAS 评测异常: {_translate_ragas_error(str(exc))}', used_metric, context_info


def _get_timeout_seconds() -> int:
    raw = os.environ.get('RAGAS_TIMEOUT_SECONDS') or Config.get_runtime_config().get('ragas_timeout_seconds') or DEFAULT_TIMEOUT_SECONDS
    try:
        return max(10, int(raw))
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT_SECONDS


def _run_with_timeout(metric_name: str, context_info: Dict[str, Any], timeout_seconds: int) -> float:
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = executor.submit(_run_ragas, metric_name, context_info)
    try:
        return future.result(timeout=timeout_seconds)
    except concurrent.futures.TimeoutError as exc:
        future.cancel()
        context_info['stage'] = 'timeout'
        raise TimeoutError(f'RAGAS {metric_name} 单条评分超过 {timeout_seconds} 秒，已终止等待。可设置 RAGAS_TIMEOUT_SECONDS 调整超时时间。') from exc
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


def _run_ragas(metric_name: str, context_info: Dict[str, Any]) -> float:
    context_info['stage'] = 'resolving_metric'
    metric = _resolve_metric(metric_name)
    context_info['stage'] = 'building_judge_models'
    llm, embeddings, model_info = _build_models(metric_name)
    context_info['model_info'] = model_info

    try:
        context_info['stage'] = 'dataset_evaluate_scoring'
        return _run_dataset_evaluate(metric, llm, embeddings, context_info)
    except Exception as exc:
        context_info['dataset_evaluate_error'] = str(exc)
        context_info['stage'] = 'single_turn_scoring'
        return _run_single_turn(metric, llm, embeddings, context_info)


def _run_single_turn(metric, llm, embeddings, context_info: Dict[str, Any]) -> float:
    from ragas import SingleTurnSample

    sample = SingleTurnSample(
        user_input=context_info['user_input'],
        response=context_info['response'],
        retrieved_contexts=context_info['contexts'],
        reference=context_info['reference'],
    )
    _attach_models(metric, llm, embeddings)

    if hasattr(metric, 'single_turn_score'):
        result = metric.single_turn_score(sample)
    elif hasattr(metric, 'single_turn_ascore'):
        result = asyncio.run(metric.single_turn_ascore(sample))
    elif hasattr(metric, 'score'):
        result = metric.score(sample)
    else:
        raise RuntimeError('当前 RAGAS metric 不支持 single-turn scoring')
    return _coerce_score(result, metric)


def _run_dataset_evaluate(metric, llm, embeddings, context_info: Dict[str, Any]) -> float:
    from datasets import Dataset
    from ragas import evaluate

    rows = [_modern_row(context_info)]
    try:
        dataset = Dataset.from_list(rows)
        result = evaluate(dataset, metrics=[metric], llm=llm, embeddings=embeddings, show_progress=False, raise_exceptions=True)
        return _extract_evaluate_score(result, metric)
    except Exception:
        dataset = Dataset.from_list([_legacy_row(context_info)])
        result = evaluate(dataset, metrics=[metric], llm=llm, embeddings=embeddings, show_progress=False, raise_exceptions=True)
        return _extract_evaluate_score(result, metric)


def _resolve_metric(metric_name: str):
    import ragas.metrics as metrics_module

    for candidate in METRIC_NAMES.get(metric_name, [metric_name]):
        if hasattr(metrics_module, candidate):
            metric = getattr(metrics_module, candidate)
            if metric is None:
                continue
            return metric() if isinstance(metric, type) else metric
    raise RuntimeError(f'当前 RAGAS 版本未暴露指标 {metric_name}')


def _build_models(metric_name: str):
    runtime = Config.get_runtime_config()
    api_key = os.environ.get('RAGAS_API_KEY') or runtime.get('ragas_api_key') or runtime.get('ark_api_key') or os.environ.get('ARK_API_KEY', '')
    base_url = os.environ.get('RAGAS_BASE_URL') or runtime.get('ragas_base_url')
    model_name = os.environ.get('RAGAS_MODEL') or runtime.get('ragas_model')
    embedding_model = os.environ.get('RAGAS_EMBEDDING_MODEL') or runtime.get('ragas_embedding_model')
    embedding_base_url = os.environ.get('RAGAS_EMBEDDING_BASE_URL') or runtime.get('ragas_embedding_base_url') or base_url

    if not api_key:
        raise RuntimeError('未配置 RAGAS_API_KEY 或 ARK_API_KEY，无法启用 RAGAS 真实评测。请在 .env 或系统设置中设置。')
    if not base_url:
        raise RuntimeError('未配置 RAGAS Base URL，RAGAS 需要独立的模型 Base URL（请在系统设置或 .env 中设置）。')
    if not model_name:
        raise RuntimeError('未配置 RAGAS 模型，RAGAS 需要独立的判分模型或 Endpoint ID（请在系统设置或 .env 中设置）。')

    os.environ['OPENAI_API_KEY'] = api_key
    if base_url:
        os.environ['OPENAI_BASE_URL'] = base_url

    # Keep these non-secret fields in the detailed log so endpoint mismatches are visible.
    # `api_key` is intentionally not recorded.
    llm = ArkOpenAIRagasLLM(api_key=api_key, base_url=base_url, model=model_name).as_ragas_llm()
    embeddings = None
    if embedding_model:
        from langchain_openai import OpenAIEmbeddings
        embeddings = OpenAIEmbeddings(model=embedding_model, api_key=api_key, base_url=embedding_base_url or None)
    return llm, embeddings, {
        'ragas_model': model_name,
        'ragas_base_url': base_url,
        'ragas_base_url_source': 'ragas_dedicated_config',
        'embedding_model': embedding_model,
        'embedding_base_url': embedding_base_url if embedding_model else None,
    }


def _attach_models(metric, llm, embeddings):
    # llm 可能已经是 ragas BaseRagasLLM 子类（如我们的 ArkOpenAIRagasLLM），
    # 若再用 LangchainLLMWrapper 包一层，wrapper 会去调 langchain 模型才有的
    # agenerate_prompt/generate_prompt，导致 answer_relevancy 等指标报
    # "'_OpenAIRagasLLM' object has no attribute 'agenerate_prompt'"。
    # 因此仅当 llm 是裸 langchain 对象时才包装。
    try:
        from ragas.embeddings import LangchainEmbeddingsWrapper
        from ragas.llms.base import BaseRagasLLM
        if isinstance(llm, BaseRagasLLM):
            wrapped_llm = llm
        else:
            from ragas.llms import LangchainLLMWrapper
            wrapped_llm = LangchainLLMWrapper(llm)
        wrapped_embeddings = LangchainEmbeddingsWrapper(embeddings) if embeddings else None
    except Exception:
        wrapped_llm = llm
        wrapped_embeddings = embeddings

    if hasattr(metric, 'llm'):
        metric.llm = wrapped_llm
    if embeddings and hasattr(metric, 'embeddings'):
        metric.embeddings = wrapped_embeddings


def _coerce_score(result, metric) -> float:
    if isinstance(result, (int, float)):
        return _validate_score(float(result))
    if isinstance(result, dict):
        for key in [_metric_result_name(metric), 'score', 'value']:
            if key in result:
                return _validate_score(float(result[key]))
    for attr in ['score', 'value']:
        if hasattr(result, attr):
            return _validate_score(float(getattr(result, attr)))
    return _validate_score(float(result))


def _extract_evaluate_score(result, metric) -> float:
    metric_key = _metric_result_name(metric)
    for key in [metric_key, getattr(metric, 'name', None), 'score']:
        if not key:
            continue
        try:
            value = result[key]
            if isinstance(value, list):
                value = value[0]
            return _validate_score(float(value))
        except Exception:
            pass

    try:
        data = result.to_pandas().to_dict(orient='records')[0]
        for key, value in data.items():
            if key in {'user_input', 'question', 'response', 'answer', 'retrieved_contexts', 'contexts', 'reference', 'ground_truth'}:
                continue
            if isinstance(value, (int, float)):
                return _validate_score(float(value))
    except Exception:
        pass

    raise RuntimeError('无法从 RAGAS evaluate 结果中读取分数')


def _validate_score(score: float) -> float:
    if math.isnan(score) or math.isinf(score):
        raise RuntimeError('RAGAS 返回了无效分数 NaN/Infinity，通常是判分模型调用失败或 embedding 配置不可用。')
    return score


def _metric_result_name(metric) -> str:
    return str(getattr(metric, 'name', None) or getattr(metric, '__name__', None) or metric.__class__.__name__).lower()


def _build_ragas_inputs(*, query: str, agent_output: str, expected: str,
                        input_payload=None, expected_payload=None, agent_output_payload=None) -> Dict[str, Any]:
    input_payload = input_payload if isinstance(input_payload, dict) else {}
    expected_payload = expected_payload if isinstance(expected_payload, dict) else {}
    agent_output_payload = agent_output_payload if isinstance(agent_output_payload, dict) else {}

    contexts, context_source = _first_contexts([
        ('input_payload.contexts', input_payload.get('contexts')),
        ('input_payload.context', input_payload.get('context')),
        ('input_payload.retrieved_contexts', input_payload.get('retrieved_contexts')),
        ('expected_payload.contexts', expected_payload.get('contexts')),
        ('expected_payload.context', expected_payload.get('context')),
        ('expected_payload.retrieved_contexts', expected_payload.get('retrieved_contexts')),
        ('agent_output_payload.contexts', agent_output_payload.get('contexts')),
        ('agent_output_payload.context', agent_output_payload.get('context')),
        ('agent_output_payload.retrieved_contexts', agent_output_payload.get('retrieved_contexts')),
    ])

    reference, reference_source = _first_text([
        ('expected_payload.reference', expected_payload.get('reference')),
        ('expected_payload.ground_truth', expected_payload.get('ground_truth')),
        ('expected_payload.answer', expected_payload.get('answer')),
        ('expected_payload.expected_output', expected_payload.get('expected_output')),
        ('expected', expected),
        ('input_payload.reference', input_payload.get('reference')),
        ('input_payload.ground_truth', input_payload.get('ground_truth')),
    ])

    user_input, input_source = _first_text([
        ('query', query),
        ('input_payload.query', input_payload.get('query')),
        ('input_payload.question', input_payload.get('question')),
    ])

    return {
        'user_input': user_input or '',
        'response': str(agent_output or ''),
        'contexts': contexts,
        'reference': reference or '',
        'context_source': context_source,
        'reference_source': reference_source,
        'input_source': input_source,
        'has_contexts': bool(contexts),
        'has_reference': bool(reference),
        'input_payload': input_payload,
        'expected_payload': expected_payload,
        'agent_output_payload': agent_output_payload,
        'ragas_used_fallback': False,
    }


def _validate_required_fields(metric_name: str, context_info: Dict[str, Any]):
    missing = []
    for field in REQUIRED_FIELDS.get(metric_name, []):
        if field == 'contexts' and not context_info.get('contexts'):
            missing.append('input_payload.contexts 或 input_payload.context')
        if field == 'reference' and not context_info.get('reference'):
            missing.append('expected_payload.reference / ground_truth 或 expected')
    if missing:
        raise RagasInputError(f'RAGAS {metric_name} 需要 {"、".join(missing)}')


def _modern_row(context_info: Dict[str, Any]) -> Dict[str, Any]:
    return {
        'user_input': context_info['user_input'],
        'response': context_info['response'],
        'retrieved_contexts': context_info['contexts'],
        'reference': context_info['reference'],
    }


def _legacy_row(context_info: Dict[str, Any]) -> Dict[str, Any]:
    return {
        'question': context_info['user_input'],
        'answer': context_info['response'],
        'contexts': context_info['contexts'],
        'ground_truth': context_info['reference'],
    }


def _first_contexts(candidates) -> Tuple[List[str], Optional[str]]:
    for source, value in candidates:
        contexts = _normalize_contexts(value)
        if contexts:
            return contexts, source
    return [], None


def _first_text(candidates) -> Tuple[str, Optional[str]]:
    for source, value in candidates:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text, source
    return '', None


def _normalize_contexts(value) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, dict):
        for key in ['text', 'content', 'page_content']:
            if value.get(key):
                return [str(value[key])]
        return [str(value)]
    if isinstance(value, list):
        contexts = []
        for item in value:
            if isinstance(item, dict):
                text = item.get('text') or item.get('content') or item.get('page_content') or str(item)
            else:
                text = str(item)
            if text.strip():
                contexts.append(text)
        return contexts
    return [str(value)] if str(value).strip() else []


def _translate_ragas_error(raw: str) -> str:
    text = raw or ''
    low = text.lower()
    # answer_relevancy / answer_correctness 等指标内部依赖 embedding 做语义相似度，
    # 未配置 RAGAS_EMBEDDING_MODEL 时 ragas 直接抛 "requires embeddings to be set"
    # 或 "AnswerSimilarity must be set"。把这类错误翻译成明确的配置指引。
    if 'requires embeddings' in low or 'embeddings to be set' in low or 'answersimilarity' in low:
        return (
            '该指标需要 embedding（向量化）模型来计算语义相似度，但当前未配置。'
            '请在 .env 中设置 RAGAS_EMBEDDING_MODEL（火山方舟可用的 embedding 模型/Endpoint ID）'
            '以及可选的 RAGAS_EMBEDDING_BASE_URL；若不需要语义相似度，可改用 faithfulness、'
            'context_precision、context_recall 等不依赖 embedding 的指标。'
        )
    if '404' in text or 'invalidendpointormodel' in low:
        return 'RAGAS 判分模型或 embedding 模型在火山方舟未开通或 Endpoint ID 错误，请检查 RAGAS_MODEL / RAGAS_BASE_URL / RAGAS_EMBEDDING_MODEL。'
    if '401' in text or 'authentication' in low or 'invalid api key' in low:
        return 'ARK_API_KEY 缺失或无效，请检查 .env / 系统设置中的密钥。'
    if 'connection' in low or 'timeout' in low:
        return '无法连接火山方舟接口，请检查网络或 ARK_BASE_URL 配置。'
    if 'rate limit' in low or '429' in text:
        return '判分模型触发了限流，请稍后再试或降低任务并发。'
    return text
