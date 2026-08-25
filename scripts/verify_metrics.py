#!/usr/bin/env python3
"""真实跑一遍各框架评分路径，验证每个指标能否正常评测。

用法: .venv/bin/python scripts/verify_metrics.py [deepeval|trulens|ragas|all]
需要在 instance/system_config.json 或 .env 中配置好 Ark 凭证。
"""
import os
import sys
import types
import time

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from app import create_app  # noqa: E402
from app.services.evaluation_engine import DeepEvalEvaluator, TruLensEvaluator, RagasEvaluator  # noqa: E402

app = create_app()


def _make_evaluator(cls):
    task = types.SimpleNamespace(selected_metrics=[])
    return cls(task)


def run_case(framework, evaluator, case):
    metric = case['metric']
    t0 = time.time()
    try:
        result = evaluator.score_output(
            agent_output=case['agent_output'],
            expected=case.get('expected', ''),
            query=case.get('query', ''),
            metric=metric,
            input_payload=case.get('input_payload'),
            expected_payload=case.get('expected_payload'),
            agent_output_payload=case.get('agent_output_payload'),
            task_case_id=None,
        )
        elapsed = round(time.time() - t0, 1)
        score, status, err, details = result
        return {
            'framework': framework, 'metric': metric, 'status': status,
            'score': score, 'elapsed_s': elapsed,
            'error': err,
            'raw_score': details.get('deepeval_raw_score') or details.get('trulens_raw_score') or details.get('ragas_raw_score'),
            'used_metric': details.get('trulens_used_metric') or details.get('ragas_used_metric'),
            'fallback': details.get('deepeval_used_fallback') or details.get('trulens_used_fallback') or details.get('ragas_used_fallback'),
            'warnings': details.get('warnings'),
            'stage': details.get('stage'),
            'hint': details.get('hint'),
        }
    except Exception as exc:  # noqa: BLE001
        return {'framework': framework, 'metric': metric, 'status': 'CRASH',
                'score': None, 'elapsed_s': round(time.time() - t0, 1),
                'error': f'{type(exc).__name__}: {exc}'}


DEEPEVAL_CASES = [
    {'metric': 'task_completion', 'query': '订明天北京到上海的机票',
     'expected': '成功完成机票预订',
     'agent_output': '已为你预订明天 08:00 国航 CA1234 北京→上海的机票，订单号 MK778。'},
    {'metric': 'goal_accuracy', 'query': '规划三天北京行程',
     'expected': '一份三天的北京行程',
     'agent_output': '第一天：天安门-故宫；第二天：长城-十三陵；第三天：颐和园-返程。'},
    {'metric': 'tsr_aro', 'query': '查一下北京天气',
     'expected': '回答天气', 'agent_output': '北京今天晴，28度。'},
    {'metric': 'tool_correctness', 'query': '北京天气',
     'expected': '调用天气工具',
     'agent_output': '北京今天晴，28度。',
     'expected_payload': {'expected_tool_calls': [{'name': 'get_weather', 'arguments': {'city': '北京'}}]},
     'agent_output_payload': {'tool_calls': [{'name': 'get_weather', 'arguments': {'city': '北京'}, 'result': {'temp': 28}}]}},
    {'metric': 'plan_quality', 'query': '先查天气再推荐穿搭',
     'expected': '合理规划', 'agent_output': '今天28度，建议穿短袖。',
     'agent_output_payload': {'trace': {'steps': [
         {'step': 1, 'action': '调用 get_weather', 'thought': '需要温度'},
         {'step': 2, 'action': '根据温度推荐穿搭'}]}}},
    {'metric': 'plan_adherence', 'query': '三句话内解释四季',
     'expected': '遵循约束', 'agent_output': '地球公转加地轴倾斜，阳光直射点南北移动，形成四季。',
     'agent_output_payload': {'trace': {'steps': [{'step': 1, 'action': '直接精简作答'}]}}},
    {'metric': 'step_efficiency', 'query': '1+1等于几',
     'expected': '一步给出', 'agent_output': '2',
     'agent_output_payload': {'trace': {'steps': [{'step': 1, 'action': '直接计算'}]}}},
    {'metric': 'geval', 'query': '小明把书给小红，然后他离开了。谁离开了？',
     'expected': '小明离开了',
     'agent_output': '离开了的是小明。',
     'expected_payload': {'name': '指代消解', 'criteria': "正确解析'他'指代为小明=通过", 'threshold': 0.5}},
    {'metric': 'hallucination', 'query': '北京多少度',
     'expected': '据数据回答', 'agent_output': '北京今天28度。',
     'input_payload': {'context': '北京市气象台：晴，气温28℃。'}},
    {'metric': 'hallucination_rate', 'query': '北京多少度',
     'expected': '据事实', 'agent_output': '北京今天28度。',
     'input_payload': {'context': '北京市气象台：晴，气温28℃。'}},
    {'metric': 'factual_consistency', 'query': '相对论年份',
     'expected': '据上下文', 'agent_output': '爱因斯坦1905年提出狭义相对论。',
     'input_payload': {'context': '爱因斯坦1905年发表狭义相对论。'}},
    {'metric': 'format_compliance', 'query': '返回北京天气JSON',
     'expected': '合法JSON', 'agent_output': '{"city":"北京","temp":28,"condition":"晴"}',
     'expected_payload': {'fields': {'city': 'str', 'temp': 'int', 'condition': 'str'},
                          'optional_fields': ['condition']}},
    {'metric': 'format_compliance_no_schema', 'query': '返回JSON',
     'expected': '合法JSON', 'agent_output': '{"any": "json", "n": [1,2]}',
     'expected_payload': {}},
]

TRULENS_CASES = [
    {'metric': 'answer_relevance', 'query': '如何重置密码？',
     'expected': '重置步骤', 'agent_output': '进入设置-账户安全-修改密码，输入旧密码后设置新密码即可。'},
    {'metric': 'context_relevance', 'query': '退款多久到账？',
     'expected': '退款政策', 'agent_output': '3-5个工作日到账。',
     'input_payload': {'context': '退款将在3-5个工作日原路返回。'}},
    {'metric': 'groundedness', 'query': '我的会员等级？',
     'expected': '依据上下文', 'agent_output': '您当前是黄金会员。',
     'input_payload': {'context': '用户当前会员等级为黄金会员，到期2025-12-31。'}},
]

RAGAS_CASES = [
    {'metric': 'answer_correctness', 'query': '法国首都？',
     'expected': '巴黎', 'agent_output': '法国的首都是巴黎。',
     'expected_payload': {'reference': '法国的首都是巴黎。'}},
    {'metric': 'answer_relevancy', 'query': '如何退货？',
     'expected': '退货流程', 'agent_output': '在订单页点击申请退货，填写原因后寄回商品。'},
    {'metric': 'faithfulness', 'query': '水的沸点？',
     'expected': '100度', 'agent_output': '标准大气压下水的沸点是100℃。',
     'input_payload': {'contexts': ['标准大气压下水的沸点为100℃。']}},
    {'metric': 'context_precision', 'query': '水的沸点？',
     'expected': '100度', 'agent_output': '水的沸点是100℃。',
     'input_payload': {'contexts': ['标准大气压下水的沸点为100℃。']},
     'expected_payload': {'reference': '标准大气压下水的沸点为100摄氏度。'}},
    {'metric': 'context_recall', 'query': '水的沸点？',
     'expected': '100度', 'agent_output': '水的沸点是100℃。',
     'input_payload': {'contexts': ['标准大气压下水的沸点为100℃。']},
     'expected_payload': {'reference': '标准大气压下水的沸点为100摄氏度。'}},
    {'metric': 'context_entity_recall', 'query': '水的沸点？',
     'expected': '100度', 'agent_output': '水的沸点是100℃。',
     'input_payload': {'contexts': ['标准大气压下水的沸点为100℃。']},
     'expected_payload': {'reference': '标准大气压下水沸点为100摄氏度。'}},
    {'metric': 'noise_sensitivity', 'query': '水的沸点？',
     'expected': '100度', 'agent_output': '水的沸点是100℃。',
     'input_payload': {'contexts': ['标准大气压下水沸点100℃。', '今天股票上涨了2%。']},
     'expected_payload': {'reference': '标准大气压下水沸点100摄氏度。'}},
]


def main():
    target = sys.argv[1] if len(sys.argv) > 1 else 'all'
    batches = []
    if target in ('deepeval', 'all'):
        batches.append(('deepeval', _make_evaluator(DeepEvalEvaluator), DEEPEVAL_CASES))
    if target in ('trulens', 'all'):
        batches.append(('trulens', _make_evaluator(TruLensEvaluator), TRULENS_CASES))
    if target in ('ragas', 'all'):
        batches.append(('ragas', _make_evaluator(RagasEvaluator), RAGAS_CASES))

    rows = []
    with app.app_context():
        for framework, evaluator, cases in batches:
            for case in cases:
                r = run_case(framework, evaluator, case)
                rows.append(r)
                mark = 'OK ' if r['status'] in ('passed', 'failed') else 'ERR'
                line = f"[{mark}] {framework:9s} {r['metric']:26s} -> {r['status']:7s} score={r['score']} ({r['elapsed_s']}s)"
                if r['fallback']:
                    line += f" FALLBACK={r['fallback']}"
                if r['used_metric']:
                    line += f" used={r['used_metric']}"
                if r['warnings']:
                    line += f" warnings={len(r['warnings'])}"
                if r['error']:
                    line += f"\n        error: {str(r['error'])[:240]}"
                if r['hint']:
                    line += f"\n        hint: {r['hint'][:200]}"
                print(line, flush=True)

    print('\n==== 汇总 ====')
    ok = [r for r in rows if r['status'] in ('passed', 'failed')]
    bad = [r for r in rows if r['status'] not in ('passed', 'failed')]
    print(f'可正常评测: {len(ok)}/{len(rows)}')
    for r in bad:
        print(f"  ✗ {r['framework']}/{r['metric']}: {r['status']} - {str(r['error'])[:200]}")
    return 1 if bad else 0


if __name__ == '__main__':
    raise SystemExit(main())
