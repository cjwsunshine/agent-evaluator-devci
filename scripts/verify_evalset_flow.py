#!/usr/bin/env python3
"""端到端验证「手动添加」和「导入文件」两种评测集创建方式。

用 Flask test client + 合法 JWT 直接打后端接口，覆盖：
1. 手动添加：POST /evaluation-sets （带 test_cases 数组）
2. 导入文件：POST /test-cases/upload 解析 JSON/CSV/XLSX，再 POST /evaluation-sets
验证两者都能创建评测集 + 用例，并校验 input_payload/expected_payload 正确落库。
"""
import os
import sys
import io
import json
import csv

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import jwt  # noqa: E402
from app import create_app  # noqa: E402
from app.config.config import Config  # noqa: E402
from app.models.models import db, User, EvaluationSet, TestCase  # noqa: E402

app = create_app()


def _user_token():
    with app.app_context():
        user = db.session.query(User).first()
        if not user:
            user = User(username='e2e_tester', role='admin')
            if hasattr(user, 'set_password'):
                user.set_password('x')
            db.session.add(user)
            db.session.commit()
        uid = user.id
    token = jwt.encode({'user_id': str(uid), 'role': 'admin'}, Config.JWT_SECRET_KEY, algorithm='HS256')
    return str(uid), token


def _auth(token):
    return {'Authorization': f'Bearer {token}'}


def _make_agent(user_id, token):
    code = (
        "def run(input_payload):\n"
        "    return {'answer': 'ok'}\n"
    )
    resp = app.test_client().post(
        '/api/agents',
        headers=_auth(token),
        json={'name': 'E2E验证Agent', 'description': 'x', 'code_content': code}
    )
    data = resp.get_json()
    return data.get('data', {}).get('id') or data.get('id')


def main():
    user_id, token = _user_token()
    c = app.test_client()
    failures = []

    # 1) 拉取工具/指标/Agent，确认接口正常（前端初始化依赖这些）
    agents = c.get('/api/agents', headers=_auth(token)).get_json()
    tools = c.get('/api/evaluation/tools', headers=_auth(token)).get_json()
    metrics = c.get('/api/evaluation/tools/deepeval/metrics', headers=_auth(token)).get_json()
    print(f"[init] agents={len(agents.get('data') or [])} tools={len(tools.get('data') or [])} deepeval_metrics_ok={bool(metrics.get('data'))}")
    if not agents.get('data'):
        # 没有 agent 就建一个
        agent_id = _make_agent(user_id, token)
        print(f"[init] created agent id={agent_id}")
    else:
        agent_id = agents['data'][0]['id']

    # ---------- 方式一：手动添加 ----------
    manual_payload = {
        'name': 'E2E_手动添加验证',
        'agent_id': agent_id,
        'evaluation_tool': 'deepeval',
        'metric': 'task_completion',
        'test_cases': [
            {
                'name': '手动用例1',
                'query': '北京天气',
                'expected': '晴',
                'tags': 'e2e',
                'input_payload': {'context': '北京今天晴'},
                'expected_payload': {'reference': '晴'},
            }
        ],
    }
    r = c.post('/api/evaluation-sets', headers=_auth(token), json=manual_payload)
    j = r.get_json()
    print(f"\n[manual] POST /evaluation-sets -> HTTP {r.status_code} success={j.get('success')} msg={j.get('message')}")
    if not j.get('success'):
        failures.append(f"手动添加创建失败: {j.get('message')}")
        manual_set_id = None
    else:
        manual_set_id = j['data']['id']
        with app.app_context():
            tcs = db.session.query(TestCase).filter_by(set_id=manual_set_id).all()
            tc = tcs[0]
            ok = (len(tcs) == 1 and tc.input_payload and tc.input_payload.get('context') == '北京今天晴'
                  and tc.expected_payload and tc.expected_payload.get('reference') == '晴'
                  and tc.metric == 'task_completion')
            print(f"[manual] 落库用例数={len(tcs)} input_payload={tc.input_payload} expected_payload={tc.expected_payload} metric={tc.metric}")
            if not ok:
                failures.append("手动添加：用例字段未正确落库")

    # ---------- 方式二：导入文件 ----------
    # 2a) 上传 JSON 文件
    json_cases = [
        {
            'name': '导入JSON用例1',
            'query': '上海天气',
            'expected': '多云',
            'tags': 'import',
            'input_payload': {'context': '上海多云'},
            'expected_payload': {'reference': '多云'},
        },
        {
            'name': '导入JSON用例2',
            'query': '广州天气',
            'expected': '雨',
            'context': '广州有雨',  # 扁平字段，应被归入 input_payload.contexts
        },
    ]
    data = {'file': (io.BytesIO(json.dumps(json_cases, ensure_ascii=False).encode('utf-8')), 'import.json')}
    r = c.post('/api/test-cases/upload', headers=_auth(token), data=data, content_type='multipart/form-data')
    j = r.get_json()
    print(f"\n[import-json] POST /test-cases/upload -> HTTP {r.status_code} success={j.get('success')} count={(j.get('data') or {}).get('total_count')}")
    if not j.get('success'):
        failures.append(f"导入JSON解析失败: {j.get('message') or j.get('error')}")
        parsed_cases = []
    else:
        parsed_cases = j['data']['test_cases']
        # 模拟前端 createEvalSetFromImport：挑选用例并补 metric
        for tc in parsed_cases:
            tc['metric'] = tc.get('metric') or 'task_completion'
        # 验证扁平 context 被归入 input_payload.contexts
        c2 = parsed_cases[1]
        print(f"[import-json] 用例2 input_payload={c2.get('input_payload')}")
        if not (c2.get('input_payload') or {}).get('contexts'):
            failures.append("导入JSON: 扁平 context 未被归入 input_payload.contexts")

    # 2b) 用解析结果创建评测集（和前端 import 流程一致）
    if parsed_cases:
        import_payload = {
            'name': 'E2E_导入文件验证',
            'agent_id': agent_id,
            'evaluation_tool': 'deepeval',
            'metric': 'task_completion',
            'test_cases': [
                {
                    'name': tc.get('name'),
                    'query': tc.get('query'),
                    'expected': tc.get('expected'),
                    'tags': tc.get('tags') or '',
                    **({'input_payload': tc['input_payload']} if tc.get('input_payload') else {}),
                    **({'expected_payload': tc['expected_payload']} if tc.get('expected_payload') else {}),
                    'metric': tc.get('metric') or 'task_completion',
                }
                for tc in parsed_cases
            ],
        }
        r = c.post('/api/evaluation-sets', headers=_auth(token), json=import_payload)
        j = r.get_json()
        print(f"[import-save] POST /evaluation-sets -> HTTP {r.status_code} success={j.get('success')} msg={j.get('message')}")
        if not j.get('success'):
            failures.append(f"导入文件创建评测集失败: {j.get('message')}")
        else:
            import_set_id = j['data']['id']
            with app.app_context():
                tcs = db.session.query(TestCase).filter_by(set_id=import_set_id).all()
                print(f"[import-save] 落库用例数={len(tcs)} (期望 {len(parsed_cases)})")
                if len(tcs) != len(parsed_cases):
                    failures.append("导入文件: 落库用例数与选择数不符")

    # 2c) 上传 CSV 文件，验证另一种格式
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=['name', 'query', 'expected', 'tags', 'context'])
    w.writeheader()
    w.writerow({'name': 'CSV用例1', 'query': '深圳天气', 'expected': '晴', 'tags': 'csv', 'context': '深圳晴'})
    data = {'file': (io.BytesIO(buf.getvalue().encode('utf-8')), 'import.csv')}
    r = c.post('/api/test-cases/upload', headers=_auth(token), data=data, content_type='multipart/form-data')
    j = r.get_json()
    print(f"\n[import-csv] POST /test-cases/upload -> HTTP {r.status_code} success={j.get('success')} count={(j.get('data') or {}).get('total_count')}")
    if not j.get('success'):
        failures.append(f"导入CSV解析失败: {j.get('message') or j.get('error')}")
    else:
        tc0 = j['data']['test_cases'][0]
        print(f"[import-csv] 用例 input_payload={tc0.get('input_payload')}")
        if not (tc0.get('input_payload') or {}).get('contexts'):
            failures.append("导入CSV: context 列未被归入 input_payload.contexts")

    # 2d) 上传 XLSX 文件
    try:
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.append(['name', 'query', 'expected', 'tags', 'context'])
        ws.append(['XLSX用例1', '杭州天气', '阴', 'xlsx', '杭州阴'])
        xbuf = io.BytesIO()
        wb.save(xbuf)
        xbuf.seek(0)
        data = {'file': (xbuf, 'import.xlsx')}
        r = c.post('/api/test-cases/upload', headers=_auth(token), data=data, content_type='multipart/form-data')
        j = r.get_json()
        print(f"\n[import-xlsx] POST /test-cases/upload -> HTTP {r.status_code} success={j.get('success')} count={(j.get('data') or {}).get('total_count')}")
        if not j.get('success'):
            failures.append(f"导入XLSX解析失败: {j.get('message') or j.get('error')}")
    except ImportError:
        print("\n[import-xlsx] openpyxl 未安装，跳过")

    # 清理
    with app.app_context():
        for sid in [manual_set_id if 'manual_set_id' in dir() else None,
                    import_set_id if 'import_set_id' in dir() else None]:
            if sid:
                db.session.query(TestCase).filter_by(set_id=sid).delete()
                db.session.query(EvaluationSet).filter_by(id=sid).delete()
        db.session.commit()

    print('\n==== 结果 ====')
    if failures:
        for f in failures:
            print(f'  ✗ {f}')
        return 1
    print('  ✓ 手动添加、导入文件(JSON/CSV/XLSX) 全部正常')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
