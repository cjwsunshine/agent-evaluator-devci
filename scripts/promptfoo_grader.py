#!/usr/bin/env python3
"""
Promptfoo Python 断言：调用火山方舟（Ark）作 LLM-as-a-judge 给一段输出打分。

被 promptfoo 通过 `assert.type=python` 调用，约定签名：
    get_assert(output: str, context: dict) -> {"pass": bool, "score": float, "reason": str}

context['vars']['__rubric'] 中携带评分标准（由 Python 端写入 promptfooconfig.js 时传入）。
"""

import json
import os
import re
import sys


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)


def get_assert(output: str, context: dict) -> dict:
    rubric = ''
    try:
        rubric = (context.get('vars', {}) or {}).get('__rubric', '') or ''
    except Exception:
        rubric = ''

    if not rubric:
        return {'pass': False, 'score': 0.0, 'reason': '缺少 rubric（评分标准）'}

    # 懒加载，避免 promptfoo dry-run 时强依赖 app
    from app.config.config import Config  # noqa: WPS433
    from openai import OpenAI

    runtime = Config.get_runtime_config()
    api_key = runtime.get('ark_api_key') or os.environ.get('ARK_API_KEY', '')
    base_url = runtime.get('ark_base_url') or os.environ.get('ARK_BASE_URL', '')
    model = runtime.get('evaluation_model') or runtime.get('execution_model') or 'deepseek-v3.2'

    if not api_key:
        return {'pass': False, 'score': 0.0, 'reason': '未配置 ARK_API_KEY，无法调用判分模型'}

    client = OpenAI(api_key=api_key, base_url=base_url)
    system_prompt = (
        '你是一个评分助手。根据用户给的评分标准（rubric）判断输出是否符合，'
        '返回严格 JSON：{"pass": true|false, "score": 0~1 之间的小数, "reason": "中文简述"}。'
        '只输出 JSON，不要任何其他文字、Markdown 标记或代码块。'
    )
    user_prompt = (
        f'<output>\n{output}\n</output>\n<rubric>\n{rubric}\n</rubric>\n请按系统消息要求评分。'
    )

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': user_prompt},
            ],
            temperature=0,
        )
        text = (resp.choices[0].message.content or '').strip()
    except Exception as exc:  # noqa: BLE001
        return {'pass': False, 'score': 0.0, 'reason': f'判分模型调用失败: {exc}'}

    parsed = _parse_grading(text)
    if parsed is None:
        return {'pass': False, 'score': 0.0, 'reason': f'判分输出无法解析: {text[:200]}'}

    score = float(parsed.get('score', 0.0))
    if score > 1:  # 容错：模型偶尔给 0~10 / 0~100
        score = score / 100.0 if score > 10 else score / 10.0
    score = max(0.0, min(1.0, score))
    return {
        'pass': bool(parsed.get('pass', score >= 0.5)),
        'score': score,
        'reason': str(parsed.get('reason', ''))[:500],
    }


def _parse_grading(text: str):
    """把模型可能的 Markdown / 文本包装剥掉，抽出 {pass,score,reason}。"""
    candidates = []
    # 直接是 JSON
    candidates.append(text)
    # 剥 Markdown code fence
    fenced = re.sub(r'^\s*```(?:json)?\s*|\s*```\s*$', '', text.strip(), flags=re.IGNORECASE)
    candidates.append(fenced)
    # 抠第一个 {...}
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        candidates.append(match.group(0))

    for cand in candidates:
        try:
            data = json.loads(cand)
            if isinstance(data, dict):
                return data
        except Exception:
            continue
    return None


if __name__ == '__main__':
    # 允许命令行直接调试: echo '<output>' | python promptfoo_grader.py "<rubric>"
    rubric = sys.argv[1] if len(sys.argv) > 1 else ''
    out = sys.stdin.read()
    print(json.dumps(get_assert(out, {'vars': {'__rubric': rubric}}), ensure_ascii=False, indent=2))
