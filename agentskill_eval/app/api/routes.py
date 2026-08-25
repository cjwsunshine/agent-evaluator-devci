from flask import Blueprint, request, jsonify
from app.models.models import db, User, TestCase, Agent, EvaluationTask, TaskTestCase, EvaluationResult
from app.services.auth_service import AuthService
from app.services.test_case_service import TestCaseService
from app.services.agent_service import AgentService
from app.services.task_service import TaskService
from app.services.report_service import ReportService
from app.services.system_service import SystemService
from app.utils.decorators import auth_required, admin_required
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
    user_id = request.headers.get('X-User-Id')
    result = TestCaseService.get_test_cases(user_id)
    return jsonify(result)

@api_bp.route('/test-cases', methods=['POST'])
@auth_required
def create_test_case():
    user_id = request.headers.get('X-User-Id')
    data = request.get_json()
    result = TestCaseService.create_test_case(user_id, data)
    return jsonify(result)

@api_bp.route('/test-cases/<int:case_id>', methods=['PUT'])
@auth_required
def update_test_case(case_id):
    user_id = request.headers.get('X-User-Id')
    data = request.get_json()
    result = TestCaseService.update_test_case(user_id, case_id, data)
    return jsonify(result)

@api_bp.route('/test-cases/<int:case_id>', methods=['DELETE'])
@auth_required
def delete_test_case(case_id):
    user_id = request.headers.get('X-User-Id')
    result = TestCaseService.delete_test_case(user_id, case_id)
    return jsonify(result)

# Agent管理接口
@api_bp.route('/agents', methods=['GET'])
@auth_required
def get_agents():
    user_id = request.headers.get('X-User-Id')
    result = AgentService.get_agents(user_id)
    return jsonify(result)

@api_bp.route('/agents', methods=['POST'])
@auth_required
def create_agent():
    user_id = request.headers.get('X-User-Id')
    data = request.get_json()
    result = AgentService.create_agent(user_id, data)
    return jsonify(result)

@api_bp.route('/agents/<int:agent_id>', methods=['PUT'])
@auth_required
def update_agent(agent_id):
    user_id = request.headers.get('X-User-Id')
    data = request.get_json()
    result = AgentService.update_agent(user_id, agent_id, data)
    return jsonify(result)

@api_bp.route('/agents/<int:agent_id>', methods=['DELETE'])
@auth_required
def delete_agent(agent_id):
    user_id = request.headers.get('X-User-Id')
    result = AgentService.delete_agent(user_id, agent_id)
    return jsonify(result)

# 评测任务管理接口
@api_bp.route('/tasks', methods=['GET'])
@auth_required
def get_tasks():
    user_id = request.headers.get('X-User-Id')
    result = TaskService.get_tasks(user_id)
    return jsonify(result)

@api_bp.route('/tasks', methods=['POST'])
@auth_required
def create_task():
    user_id = request.headers.get('X-User-Id')
    data = request.get_json()
    result = TaskService.create_task(user_id, data)
    return jsonify(result)

@api_bp.route('/tasks/<int:task_id>/start', methods=['POST'])
@auth_required
def start_task(task_id):
    user_id = request.headers.get('X-User-Id')
    result = TaskService.start_task(user_id, task_id)
    return jsonify(result)

@api_bp.route('/tasks/<int:task_id>/stop', methods=['POST'])
@auth_required
def stop_task(task_id):
    user_id = request.headers.get('X-User-Id')
    result = TaskService.stop_task(user_id, task_id)
    return jsonify(result)

@api_bp.route('/tasks/<int:task_id>/status', methods=['GET'])
@auth_required
def get_task_status(task_id):
    user_id = request.headers.get('X-User-Id')
    result = TaskService.get_task_status(user_id, task_id)
    return jsonify(result)

# 报告生成接口
@api_bp.route('/reports/<int:task_id>', methods=['GET'])
@auth_required
def get_report(task_id):
    user_id = request.headers.get('X-User-Id')
    result = ReportService.generate_report(user_id, task_id)
    return jsonify(result)

@api_bp.route('/reports/<int:task_id>/export', methods=['POST'])
@auth_required
def export_report(task_id):
    user_id = request.headers.get('X-User-Id')
    data = request.get_json()
    result = ReportService.export_report(user_id, task_id, data)
    return jsonify(result)

# 系统配置接口
@api_bp.route('/system/config', methods=['GET'])
@admin_required
def get_system_config():
    result = SystemService.get_config()
    return jsonify(result)

@api_bp.route('/system/config', methods=['PUT'])
@admin_required
def update_system_config():
    data = request.get_json()
    result = SystemService.update_config(data)
    return jsonify(result)

# Promptfoo配置接口
@api_bp.route('/promptfoo/config', methods=['GET'])
@auth_required
def get_promptfoo_config():
    config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'promptfooconfig.js')
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
    config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'promptfooconfig.js')
    try:
        with open(config_path, 'w', encoding='utf-8') as f:
            f.write(config_content)
        return jsonify({'success': True, 'message': '配置已更新'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@api_bp.route('/promptfoo/run', methods=['POST'])
@auth_required
def run_promptfoo():
    user_id = request.headers.get('X-User-Id')
    data = request.get_json() or {}

    agent_id = data.get('agentId')
    test_case_ids = data.get('testCaseIds', [])

    base_dir = os.path.dirname(os.path.dirname(__file__))
    node_path = os.path.expanduser('~/node-v20.20.0-darwin-arm64/bin/node')
    npm_path = os.path.expanduser('~/node-v20.20.0-darwin-arm64/bin/npm')
    npx_path = os.path.expanduser('~/node-v20.20.0-darwin-arm64/bin/npx')

    env = os.environ.copy()
    env['PATH'] = f"{os.path.dirname(npx_path)}:{env.get('PATH', '')}"

    try:
        result = subprocess.run(
            [npx_path, 'promptfoo', 'eval', '--config', 'promptfooconfig.js', '--output', 'results/promptfoo/results.json'],
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
    base_dir = os.path.dirname(os.path.dirname(__file__))
    results_path = os.path.join(base_dir, 'results', 'promptfoo', 'results.json')
    try:
        with open(results_path, 'r', encoding='utf-8') as f:
            results = json.load(f)
        return jsonify({'success': True, 'data': results})
    except FileNotFoundError:
        return jsonify({'success': False, 'error': '结果文件不存在'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})