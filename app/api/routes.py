from flask import Blueprint, request, jsonify
from app.models.models import db, User, TestCase, EvaluationSet, Agent, EvaluationTask, TaskTestCase, EvaluationResult
from app.services.auth_service import AuthService
from app.services.test_case_service import TestCaseService
from app.services.agent_service import AgentService
from app.services.task_service import TaskService
from app.services.report_service import ReportService
from app.services.system_service import SystemService
from app.utils.decorators import auth_required, admin_required
from app.config.config import Config
import subprocess
import os
import json

api_bp = Blueprint('api', __name__)

# 认证相关接口
@api_bp.route('/auth/register', methods=['POST'])
def register():
    data = request.get_json()
    result = AuthService.register(data)
    return jsonify(result)

@api_bp.route('/auth/login', methods=['POST'])
def login():
    data = request.get_json()
    result = AuthService.login(data)
    return jsonify(result)

# 测试用例管理接口
@api_bp.route('/test-cases', methods=['GET'])
@auth_required
def get_test_cases():
    user_id = request.environ.get('X-User-Id')
    result = TestCaseService.get_test_cases(user_id)
    return jsonify(result)

@api_bp.route('/test-cases', methods=['POST'])
@auth_required
def create_test_case():
    user_id = request.environ.get('X-User-Id')
    data = request.get_json()
    result = TestCaseService.create_test_case(user_id, data)
    return jsonify(result)

@api_bp.route('/test-cases/<int:case_id>', methods=['PUT'])
@auth_required
def update_test_case(case_id):
    user_id = request.environ.get('X-User-Id')
    data = request.get_json()
    result = TestCaseService.update_test_case(user_id, case_id, data)
    return jsonify(result)

@api_bp.route('/test-cases/<int:case_id>', methods=['DELETE'])
@auth_required
def delete_test_case(case_id):
    user_id = request.environ.get('X-User-Id')
    result = TestCaseService.delete_test_case(user_id, case_id)
    return jsonify(result)

# 评测集管理接口
@api_bp.route('/evaluation-sets', methods=['GET'])
@auth_required
def get_evaluation_sets():
    user_id = request.environ.get('X-User-Id')
    result = TestCaseService.get_evaluation_sets(user_id)
    return jsonify(result)

@api_bp.route('/evaluation-sets', methods=['POST'])
@auth_required
def create_evaluation_set():
    user_id = request.environ.get('X-User-Id')
    data = request.get_json()
    result = TestCaseService.create_evaluation_set(user_id, data)
    return jsonify(result)

@api_bp.route('/evaluation-sets/<path:virtual_id>/materialize', methods=['POST'])
@auth_required
def materialize_evaluation_set(virtual_id):
    user_id = request.environ.get('X-User-Id')
    data = request.get_json()
    result = TestCaseService.materialize_evaluation_set(user_id, virtual_id, data)
    return jsonify(result)

@api_bp.route('/evaluation-sets/<int:set_id>', methods=['PUT'])
@auth_required
def update_evaluation_set(set_id):
    user_id = request.environ.get('X-User-Id')
    data = request.get_json()
    result = TestCaseService.update_evaluation_set(user_id, set_id, data)
    return jsonify(result)

@api_bp.route('/evaluation-sets/<path:set_id>', methods=['DELETE'])
@auth_required
def delete_evaluation_set(set_id):
    user_id = request.environ.get('X-User-Id')
    result = TestCaseService.delete_evaluation_set(user_id, set_id)
    return jsonify(result)

@api_bp.route('/evaluation-sets/<int:set_id>/copy', methods=['POST'])
@auth_required
def copy_evaluation_set(set_id):
    user_id = request.environ.get('X-User-Id')
    result = TestCaseService.copy_evaluation_set(user_id, set_id)
    return jsonify(result)

@api_bp.route('/evaluation-sets/<int:set_id>/download', methods=['GET'])
@auth_required
def download_evaluation_set(set_id):
    user_id = request.environ.get('X-User-Id')
    evaluation_set = db.session.query(EvaluationSet).filter_by(id=set_id, user_id=user_id).first()
    if not evaluation_set:
        return jsonify({'success': False, 'message': '评测集不存在'})
    return jsonify({
        'success': True,
        'data': {
            'name': evaluation_set.name,
            'agent_id': evaluation_set.agent_id,
            'evaluation_tool': evaluation_set.evaluation_tool,
            'test_cases': [{
                'name': case.name,
                'query': case.query,
                'expected': case.expected,
                'tags': case.tags,
                'metric': case.metric,
                'input_payload': case.input_payload,
                'expected_payload': case.expected_payload
            } for case in evaluation_set.test_cases]
        }
    })

# Agent管理接口
@api_bp.route('/agents', methods=['GET'])
@auth_required
def get_agents():
    user_id = request.environ.get('X-User-Id')
    result = AgentService.get_agents(user_id)
    return jsonify(result)

@api_bp.route('/agents', methods=['POST'])
@auth_required
def create_agent():
    user_id = request.environ.get('X-User-Id')
    data = request.get_json()
    result = AgentService.create_agent(user_id, data)
    return jsonify(result)

@api_bp.route('/agents/<int:agent_id>', methods=['PUT'])
@auth_required
def update_agent(agent_id):
    user_id = request.environ.get('X-User-Id')
    data = request.get_json()
    result = AgentService.update_agent(user_id, agent_id, data)
    return jsonify(result)

@api_bp.route('/agents/<int:agent_id>', methods=['DELETE'])
@auth_required
def delete_agent(agent_id):
    user_id = request.environ.get('X-User-Id')
    result = AgentService.delete_agent(user_id, agent_id)
    return jsonify(result)

# 评测任务管理接口
@api_bp.route('/tasks', methods=['GET'])
@auth_required
def get_tasks():
    user_id = request.environ.get('X-User-Id')
    result = TaskService.get_tasks(user_id)
    return jsonify(result)

@api_bp.route('/tasks', methods=['POST'])
@auth_required
def create_task():
    user_id = request.environ.get('X-User-Id')
    data = request.get_json()
    result = TaskService.create_task(user_id, data)
    return jsonify(result)

@api_bp.route('/tasks/<int:task_id>/start', methods=['POST'])
@auth_required
def start_task(task_id):
    user_id = request.environ.get('X-User-Id')
    result = TaskService.start_task(user_id, task_id)
    return jsonify(result)

@api_bp.route('/tasks/<int:task_id>/restart', methods=['POST'])
@auth_required
def restart_task(task_id):
    user_id = request.environ.get('X-User-Id')
    result = TaskService.restart_task(user_id, task_id)
    return jsonify(result)

@api_bp.route('/tasks/<int:task_id>/stop', methods=['POST'])
@auth_required
def stop_task(task_id):
    user_id = request.environ.get('X-User-Id')
    result = TaskService.stop_task(user_id, task_id)
    return jsonify(result)

@api_bp.route('/tasks/<int:task_id>', methods=['DELETE'])
@auth_required
def delete_task(task_id):
    user_id = request.environ.get('X-User-Id')
    result = TaskService.delete_task(user_id, task_id)
    return jsonify(result)

@api_bp.route('/tasks/<int:task_id>/status', methods=['GET'])
@auth_required
def get_task_status(task_id):
    user_id = request.environ.get('X-User-Id')
    result = TaskService.get_task_status(user_id, task_id)
    return jsonify(result)

# 报告生成接口
@api_bp.route('/reports', methods=['GET'])
@auth_required
def list_reports():
    user_id = request.environ.get('X-User-Id')
    raw_evaluation_set_id = request.args.get('evaluation_set_id')
    if raw_evaluation_set_id == '__none':
        evaluation_set_id = '__none'
    else:
        evaluation_set_id = request.args.get('evaluation_set_id', type=int)
    agent_id = request.args.get('agent_id', type=int)
    tool_name = request.args.get('tool_name')
    result = ReportService.list_reports(user_id, evaluation_set_id, agent_id, tool_name)
    return jsonify(result)

@api_bp.route('/reports/filters', methods=['GET'])
@auth_required
def get_report_filters():
    user_id = request.environ.get('X-User-Id')
    result = ReportService.get_report_filters(user_id)
    return jsonify(result)

@api_bp.route('/reports/summary', methods=['GET'])
@auth_required
def get_report_summary():
    user_id = request.environ.get('X-User-Id')
    result = ReportService.get_overall_summary(user_id)
    return jsonify(result)

@api_bp.route('/reports/<int:task_id>', methods=['GET'])
@auth_required
def get_report(task_id):
    user_id = request.environ.get('X-User-Id')
    result = ReportService.generate_report(user_id, task_id)
    return jsonify(result)

@api_bp.route('/reports/<int:task_id>/export', methods=['POST'])
@auth_required
def export_report(task_id):
    user_id = request.environ.get('X-User-Id')
    data = request.get_json()
    result = ReportService.export_report(user_id, task_id, data)
    return jsonify(result)

# 系统配置接口
@api_bp.route('/system/config', methods=['GET'])
@auth_required
@admin_required
def get_system_config():
    result = SystemService.get_config()
    return jsonify(result)

@api_bp.route('/system/config', methods=['PUT'])
@auth_required
@admin_required
def update_system_config():
    data = request.get_json()
    result = SystemService.update_config(data)
    return jsonify(result)

# Promptfoo配置接口
@api_bp.route('/promptfoo/config', methods=['GET'])
@auth_required
def get_promptfoo_config():
    config_path = os.path.join(Config.BASE_DIR, 'promptfooconfig.js')
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            content = f.read()
        return jsonify({'success': True, 'data': content})
    except FileNotFoundError:
        return jsonify({'success': False, 'error': '配置文件不存在'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@api_bp.route('/promptfoo/config', methods=['PUT'])
@auth_required
def update_promptfoo_config():
    data = request.get_json()
    config_content = data.get('config', '')
    config_path = os.path.join(Config.BASE_DIR, 'promptfooconfig.js')
    try:
        with open(config_path, 'w', encoding='utf-8') as f:
            f.write(config_content)
        return jsonify({'success': True, 'message': '配置已更新'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@api_bp.route('/promptfoo/run', methods=['POST'])
@auth_required
def run_promptfoo():
    user_id = request.environ.get('X-User-Id')
    data = request.get_json() or {}

    agent_id = data.get('agentId')
    test_case_ids = data.get('testCaseIds', [])

    base_dir = Config.BASE_DIR
    runtime_config = Config.get_runtime_config()
    promptfoo_cmd = Config.resolve_promptfoo_command(runtime_config.get('promptfoo_path'))

    env = os.environ.copy()

    try:
        result = subprocess.run(
            [promptfoo_cmd, 'eval', '--config', 'promptfooconfig.js', '--output', 'results/promptfoo/results.json'],
            cwd=base_dir,
            capture_output=True,
            text=True,
            timeout=300,
            env=env
        )

        results_path = os.path.join(base_dir, 'results', 'promptfoo', 'results.json')
        if os.path.exists(results_path):
            with open(results_path, 'r', encoding='utf-8') as f:
                results = json.load(f)
            return jsonify({'success': True, 'results': results})

        return jsonify({
            'success': True,
            'stdout': result.stdout,
            'stderr': result.stderr,
            'returncode': result.returncode
        })
    except subprocess.TimeoutExpired:
        return jsonify({'success': False, 'error': '评估超时'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@api_bp.route('/promptfoo/results', methods=['GET'])
@auth_required
def get_promptfoo_results():
    base_dir = Config.BASE_DIR
    results_path = os.path.join(base_dir, 'results', 'promptfoo', 'results.json')
    try:
        with open(results_path, 'r', encoding='utf-8') as f:
            results = json.load(f)
        return jsonify({'success': True, 'data': results})
    except FileNotFoundError:
        return jsonify({'success': False, 'error': '结果文件不存在'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


# ==================== 评测工具管理接口 ====================

@api_bp.route('/evaluation/tools', methods=['GET'])
@auth_required
def get_evaluation_tools():
    """获取支持的评测工具列表"""
    from app.services.evaluation_engine import EvaluationEngine
    tools = EvaluationEngine.get_available_tools()
    return jsonify({'success': True, 'data': tools})


@api_bp.route('/evaluation/tools/<tool_name>/metrics', methods=['GET'])
@auth_required
def get_tool_metrics(tool_name):
    """获取指定评测工具支持的指标"""
    from app.services.evaluation_engine import DeepEvalEvaluator, PromptfooEvaluator, TruLensEvaluator, RagasEvaluator
    evaluators = {
        'deepeval': DeepEvalEvaluator,
        'promptfoo': PromptfooEvaluator,
        'trulens': TruLensEvaluator,
        'ragas': RagasEvaluator
    }
    if tool_name not in evaluators:
        return jsonify({'success': False, 'error': '不支持的评测工具'})
    
    phase = request.args.get('phase')
    metrics = evaluators[tool_name].get_available_metrics(phase)
    return jsonify({'success': True, 'data': metrics})

@api_bp.route('/evaluation/tools/<tool_name>/phases', methods=['GET'])
@auth_required
def get_tool_phases(tool_name):
    """获取指定评测工具支持的阶段列表"""
    from app.services.evaluation_engine import DeepEvalEvaluator, PromptfooEvaluator
    evaluators = {
        'deepeval': DeepEvalEvaluator,
        'promptfoo': PromptfooEvaluator
    }
    if tool_name in evaluators:
        phases = evaluators[tool_name].get_phases()
        return jsonify({'success': True, 'data': phases})
    return jsonify({'success': True, 'data': []})


# ==================== 测试用例文件上传接口 ====================

@api_bp.route('/test-cases/upload', methods=['POST'])
@auth_required
def upload_test_cases():
    """上传测试用例文件"""
    user_id = request.environ.get('X-User-Id')
    if 'file' not in request.files:
        return jsonify({'success': False, 'error': '未提供文件'})
    file = request.files['file']
    result = TestCaseService.upload_test_cases_file(user_id, file)
    return jsonify(result)


@api_bp.route('/test-cases/sample/excel', methods=['POST'])
@auth_required
def download_test_cases_excel_sample():
    """根据前端当前样例生成 Excel(.xlsx) 模板供下载"""
    from flask import send_file
    import io
    data = request.get_json(silent=True) or {}
    rows = data.get('rows')
    if not isinstance(rows, list):
        rows = [rows] if isinstance(rows, dict) else []
    content = TestCaseService.build_excel_sample(rows)
    return send_file(
        io.BytesIO(content),
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name='test_cases_sample.xlsx'
    )


@api_bp.route('/test-cases/upload/confirm', methods=['POST'])
@auth_required
def confirm_test_cases_import():
    """确认并导入测试用例"""
    user_id = request.environ.get('X-User-Id')
    data = request.get_json()
    filename = data.get('filename')
    selected_indices = data.get('selected_indices')
    agent_id = data.get('agent_id')
    evaluation_tool = data.get('evaluation_tool', 'deepeval')
    metric = data.get('metric')
    result = TestCaseService.confirm_import(user_id, filename, selected_indices, agent_id, evaluation_tool, metric)
    return jsonify(result)


@api_bp.route('/test-cases/batch', methods=['POST'])
@auth_required
def batch_import_test_cases():
    """批量导入测试用例"""
    user_id = request.environ.get('X-User-Id')
    data = request.get_json()
    test_cases = data.get('test_cases', [])
    result = TestCaseService.batch_import(user_id, test_cases)
    return jsonify(result)


# ==================== Agent 脚本上传与测试接口 ====================

@api_bp.route('/agents/<int:agent_id>/upload', methods=['POST'])
@auth_required
def upload_agent_script(agent_id):
    """上传Agent脚本文件"""
    user_id = request.environ.get('X-User-Id')
    if 'file' not in request.files:
        return jsonify({'success': False, 'error': '未提供文件'})
    file = request.files['file']
    result = AgentService.upload_agent_script(user_id, agent_id, file)
    return jsonify(result)


@api_bp.route('/agents/<int:agent_id>/test', methods=['POST'])
@auth_required
def test_agent(agent_id):
    """测试Agent连接"""
    user_id = request.environ.get('X-User-Id')
    data = request.get_json() or {}
    test_input = data.get('input', '你好')
    result = AgentService.test_agent_connection(user_id, agent_id, test_input)
    return jsonify(result)


@api_bp.route('/agents/<int:agent_id>/call', methods=['POST'])
@auth_required
def call_agent(agent_id):
    """调用Agent"""
    user_id = request.environ.get('X-User-Id')
    data = request.get_json()
    query = data.get('query', '')
    result = AgentService.call_agent(agent_id, query)
    return jsonify(result)


# ==================== PikoCI 持续评测流水线 ====================

@api_bp.route('/pipeline/selection', methods=['GET'])
@auth_required
def get_pipeline_selection():
    """获取评测范围（工具开关 + 指标勾选）及可选指标目录"""
    from app.services.pipeline_service import get_selection_view
    return jsonify({'success': True, 'data': get_selection_view()})


@api_bp.route('/pipeline/target', methods=['GET'])
@auth_required
def get_pipeline_target():
    """获取可选 Agent / 评测集，以及当前选中的目标"""
    from app.services.pipeline_service import list_targets
    user_id = request.environ.get('X-User-Id')
    return jsonify({'success': True, 'data': list_targets(user_id)})


@api_bp.route('/pipeline/target', methods=['PUT'])
@auth_required
def save_pipeline_target():
    """选择被测 Agent 与评测集，落盘供下次 Trigger 使用（无需重启 PikoCI）"""
    from app.services.pipeline_service import save_target
    user_id = request.environ.get('X-User-Id')
    data = request.get_json() or {}
    agent_id = str(data.get('agent_id') or 'builtin')
    evalset_id = str(data.get('evalset_id') or 'builtin')
    try:
        saved = save_target(user_id, agent_id, evalset_id)
        return jsonify({'success': True, 'message': '评测对象已保存', 'data': saved})
    except Exception as e:
        return jsonify({'success': False, 'message': f'保存失败: {e}'}), 400


@api_bp.route('/pipeline/target/from-task/<int:task_id>', methods=['POST'])
@auth_required
def save_pipeline_target_from_task(task_id):
    """把某个评测任务的 Agent + 用例直接设为持续评测对象，并预选其工具/指标。"""
    from app.services.pipeline_service import save_target_from_task
    user_id = request.environ.get('X-User-Id')
    try:
        saved = save_target_from_task(user_id, task_id)
        return jsonify({'success': True, 'message': '已带入持续评测', 'data': saved})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 400


@api_bp.route('/pipeline/selection', methods=['PUT'])
@auth_required
def save_pipeline_selection():
    """保存评测范围到 eval_data/selection.json（下次 Trigger 生效，无需重启）"""
    from app.services.pipeline_service import save_selection
    data = request.get_json() or {}
    try:
        saved = save_selection(data)
        return jsonify({'success': True, 'message': '评测范围已保存', 'data': saved})
    except Exception as e:
        return jsonify({'success': False, 'message': f'保存失败: {e}'}), 500


@api_bp.route('/pipeline/trigger', methods=['POST'])
@auth_required
def trigger_pipeline():
    """触发一次 PikoCI evaluate 构建（使用当前 selection.json）"""
    from app.services.pipeline_service import trigger_build
    result = trigger_build()
    code = 200 if result.get('success') else 502
    return jsonify(result), code


@api_bp.route('/pipeline/builds', methods=['GET'])
@auth_required
def list_pipeline_builds():
    """最近的构建历史（不含日志）"""
    from app.services.pipeline_service import list_builds
    limit = request.args.get('limit', default=10, type=int)
    return jsonify({'success': True, 'data': list_builds(limit=limit)})


@api_bp.route('/pipeline/builds/<build_number>', methods=['GET'])
@auth_required
def get_pipeline_build(build_number):
    """单次构建详情（含每个 task 的状态、耗时、日志）"""
    from app.services.pipeline_service import get_build
    build = get_build(build_number)
    if build is None:
        return jsonify({'success': False, 'message': '构建不存在或 PikoCI 不可达'}), 404
    return jsonify({'success': True, 'data': build})


@api_bp.route('/pipeline/reports', methods=['GET'])
@auth_required
def list_pipeline_reports():
    """列出磁盘上已生成 HTML 报告的持续评测构建（最近 20 条）。"""
    from app.services.pipeline_service import list_reports
    return jsonify({'success': True, 'data': list_reports(limit=20)})


@api_bp.route('/pipeline/report/latest', methods=['GET'])
@auth_required
def latest_pipeline_report():
    """最新一次生成的 HTML 报告位置及综合分数"""
    from app.services.pipeline_service import latest_report
    report = latest_report()
    if report is None:
        return jsonify({'success': False, 'message': '暂无报告'})
    return jsonify({'success': True, 'data': report})
