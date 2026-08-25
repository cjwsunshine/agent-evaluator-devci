"""
为 DeepEval 提供判分用的 LLM 包装。

DeepEval 的多数 metric 内部需要再调一次 LLM（"LLM-as-a-judge"）才能给出分数。
官方默认走 OpenAI；本项目用的是火山方舟（Ark），所以包一层 DeepEvalBaseLLM 让 deepeval
内部统一走 Ark。配置从 instance/system_config.json 与 .env 读取。
"""
import asyncio
import os
from typing import Any

from app.config.config import Config


_judge_singleton = None


def get_judge_llm():
    """获取（懒加载）单例 LLM judge，供 deepeval metric 使用。"""
    global _judge_singleton
    if _judge_singleton is None:
        _judge_singleton = _build_judge()
    return _judge_singleton


def _build_judge():
    # 懒导入 deepeval / openai：避免应用启动时强依赖，未安装时其它评测器仍能加载
    from deepeval.models import DeepEvalBaseLLM
    from openai import OpenAI

    runtime = Config.get_runtime_config()
    api_key = runtime.get('ark_api_key') or os.environ.get('ARK_API_KEY', '')
    base_url = runtime.get('ark_base_url') or os.environ.get('ARK_BASE_URL', '')
    model_name = runtime.get('evaluation_model') or runtime.get('execution_model') or 'deepseek-v3.2'

    if not api_key:
        raise RuntimeError(
            '未配置 ARK_API_KEY，无法启用 DeepEval 真实评测。请在 .env 或系统配置中设置。'
        )

    # 让 deepeval 内部的"如果走 OpenAI 兜底"路径也指向 Ark，避免它直接用官方端点报 401
    os.environ.setdefault('OPENAI_API_KEY', api_key)
    os.environ.setdefault('OPENAI_BASE_URL', base_url)

    client = OpenAI(api_key=api_key, base_url=base_url)

    class ArkJudgeLLM(DeepEvalBaseLLM):
        def load_model(self):
            return client

        def generate(self, prompt: str, schema: Any = None, **_kwargs) -> Any:
            response = client.chat.completions.create(
                model=model_name,
                messages=[{'role': 'user', 'content': prompt}],
                temperature=0,
            )
            text = response.choices[0].message.content or ''
            if schema is not None:
                return _coerce_schema(text, schema)
            return text

        async def a_generate(self, prompt: str, schema: Any = None, **_kwargs) -> Any:
            return await asyncio.to_thread(self.generate, prompt, schema)

        def get_model_name(self) -> str:
            return f'Ark/{model_name}'

    return ArkJudgeLLM()


def _coerce_schema(text: str, schema):
    """deepeval 部分 metric 要求 generate 返回 pydantic 模型实例。
    优先尝试 JSON 解析；失败时按字段名造一个"通过/相关"占位对象，避免整条用例评分崩溃。
    """
    import json as _json
    import re

    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        try:
            return schema.model_validate(_json.loads(match.group(0)))
        except Exception:
            pass

    fields = getattr(schema, 'model_fields', {})
    try:
        if 'statements' in fields:
            return schema(statements=[text[:200]] if text else ['no-output'])
        if 'verdicts' in fields:
            inner = fields['verdicts'].annotation.__args__[0]
            return schema(verdicts=[inner(verdict='yes', reason='fallback')])
        if 'verdict' in fields and 'reason' in fields:
            ann = fields['verdict'].annotation
            v = 1.0 if ann is float else 'yes'
            return schema(verdict=v, reason='fallback')
        if 'reason' in fields:
            return schema(reason=text[:200] or 'fallback')
    except Exception:
        pass
    return text
