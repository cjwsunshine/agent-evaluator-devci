from app.models.models import db, Agent, EvaluationSet, TestCase, EvaluationTask, TaskTestCase, EvaluationResult
from app.utils.timeutil import iso_utc
import json
import requests
import importlib.util
import os
import sys
from typing import Dict, Any
from werkzeug.utils import secure_filename


class AgentService:
    UPLOAD_FOLDER = 'agents_uploads'
    ALLOWED_EXTENSIONS = {'py'}

    @staticmethod
    def _allowed_file(filename: str) -> bool:
        return '.' in filename and filename.rsplit('.', 1)[1].lower() in AgentService.ALLOWED_EXTENSIONS

    @staticmethod
    def get_agents(user_id):
        try:
            agents = Agent.query.filter_by(user_id=user_id).all()
            result = []
            for agent in agents:
                config = json.loads(agent.access_config) if agent.access_config else {}
                display_status = 'active' if agent.is_active else 'inactive'
                result.append({
                    'id': agent.id,
                    'name': agent.name,
                    'version': agent.version,
                    'access_type': agent.access_type,
                    'script_file': agent.script_file,
                    'entry_function': agent.entry_function,
                    'api_endpoint': agent.api_endpoint,
                    'api_method': agent.api_method,
                    'api_headers': agent.api_headers,
                    'api_request_mapping': agent.api_request_mapping,
                    'is_active': agent.is_active,
                    'status': config.get('status', display_status),
                    'created_at': iso_utc(agent.created_at)
                })
            return {'success': True, 'data': result}
        except Exception as e:
            return {'success': False, 'message': str(e)}

    @staticmethod
    def create_agent(user_id, data):
        try:
            access_type = data.get('access_type', 'api')
            # 注意：生产环境使用 script 类型 Agent 建议配置白名单或签名校验

            api_key = data.get('api_key')
            api_headers = data.get('api_headers') or {}
            if api_key:
                api_headers = dict(api_headers)
                api_headers.setdefault('Authorization', f'Bearer {api_key}')

            agent = Agent(
                user_id=user_id,
                name=data.get('name'),
                version=data.get('version', '1.0.0'),
                access_type=access_type,
                script_file=data.get('script_file'),
                entry_function=data.get('entry_function', 'run_agent'),
                api_endpoint=data.get('api_endpoint'),
                api_method=data.get('api_method', 'POST'),
                api_headers=api_headers or None,
                api_request_mapping=data.get('api_request_mapping'),
                api_response_mapping=data.get('api_response_mapping'),
                is_active=data.get('is_active', True)
            )
            db.session.add(agent)
            db.session.commit()
            return {'success': True, 'message': 'Agent创建成功', 'data': {'id': agent.id}}
        except Exception as e:
            db.session.rollback()
            return {'success': False, 'message': str(e)}

    @staticmethod
    def upload_agent_script(user_id, agent_id, file):
        """上传Agent脚本文件"""
        try:
            if not file or not AgentService._allowed_file(file.filename):
                return {'success': False, 'message': '不支持的文件类型，仅支持.py文件'}

            agent = Agent.query.filter_by(id=agent_id, user_id=user_id).first()
            if not agent:
                return {'success': False, 'message': 'Agent不存在'}

            # 确保上传目录存在
            upload_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                AgentService.UPLOAD_FOLDER
            )
            os.makedirs(upload_dir, exist_ok=True)

            filename = secure_filename(f"agent_{agent_id}_{file.filename}")
            filepath = os.path.join(upload_dir, filename)
            file.save(filepath)

            agent.script_file = filename
            db.session.commit()

            return {'success': True, 'message': '脚本上传成功', 'data': {'filename': filename}}
        except Exception as e:
            db.session.rollback()
            return {'success': False, 'message': str(e)}

    @staticmethod
    def update_agent(user_id, agent_id, data):
        try:
            agent = Agent.query.filter_by(id=agent_id, user_id=user_id).first()
            if not agent:
                return {'success': False, 'message': 'Agent不存在'}

            requested_access_type = data.get('access_type', agent.access_type)

            api_headers = data.get('api_headers')
            api_key = data.get('api_key')
            if api_key:
                api_headers = dict(api_headers or agent.api_headers or {})
                api_headers['Authorization'] = f'Bearer {api_key}'

            if 'name' in data:
                agent.name = data['name']
            if 'version' in data:
                agent.version = data['version']
            if 'access_type' in data:
                agent.access_type = data['access_type']
            if 'entry_function' in data:
                agent.entry_function = data['entry_function']
            if 'api_endpoint' in data:
                agent.api_endpoint = data['api_endpoint']
            if 'api_method' in data:
                agent.api_method = data['api_method']
            if api_headers is not None:
                agent.api_headers = api_headers
            if 'api_request_mapping' in data:
                agent.api_request_mapping = data['api_request_mapping']
            if 'api_response_mapping' in data:
                agent.api_response_mapping = data['api_response_mapping']
            if 'is_active' in data:
                agent.is_active = data['is_active']

            db.session.commit()
            return {'success': True, 'message': 'Agent更新成功'}
        except Exception as e:
            db.session.rollback()
            return {'success': False, 'message': str(e)}

    @staticmethod
    def delete_agent(user_id, agent_id):
        try:
            agent = Agent.query.filter_by(id=agent_id, user_id=user_id).first()
            if not agent:
                return {'success': False, 'message': 'Agent不存在'}

            evaluation_sets = EvaluationSet.query.filter_by(agent_id=agent_id, user_id=user_id).all()
            for evaluation_set in evaluation_sets:
                for case in list(evaluation_set.test_cases):
                    task_cases = TaskTestCase.query.filter_by(test_case_id=case.id).all()
                    for task_case in task_cases:
                        EvaluationResult.query.filter_by(task_case_id=task_case.id).delete()
                        db.session.delete(task_case)
                    db.session.delete(case)
                db.session.delete(evaluation_set)

            orphan_cases = db.session.query(TestCase).filter_by(agent_id=agent_id, user_id=user_id, set_id=None).all()
            for case in orphan_cases:
                task_cases = TaskTestCase.query.filter_by(test_case_id=case.id).all()
                for task_case in task_cases:
                    EvaluationResult.query.filter_by(task_case_id=task_case.id).delete()
                    db.session.delete(task_case)
                db.session.delete(case)

            tasks = EvaluationTask.query.filter_by(agent_id=agent_id, user_id=user_id).all()
            for task in tasks:
                for task_case in list(task.task_cases):
                    EvaluationResult.query.filter_by(task_case_id=task_case.id).delete()
                    db.session.delete(task_case)
                db.session.delete(task)

            # 删除关联的脚本文件
            if agent.script_file:
                filepath = os.path.join(
                    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                    AgentService.UPLOAD_FOLDER,
                    agent.script_file
                )
                if os.path.exists(filepath):
                    os.remove(filepath)

            db.session.delete(agent)
            db.session.commit()
            return {'success': True, 'message': 'Agent删除成功'}
        except Exception as e:
            db.session.rollback()
            return {'success': False, 'message': str(e)}

    @staticmethod
    def test_agent_connection(user_id, agent_id, test_input: str = "你好") -> Dict[str, Any]:
        """测试Agent连接可用性"""
        try:
            agent = Agent.query.filter_by(id=agent_id, user_id=user_id).first()
            if not agent:
                return {'success': False, 'message': 'Agent不存在'}

            result = AgentService.call_agent(agent_id, test_input)
            return {
                'success': result.get('success', False),
                'message': '连接测试成功' if result.get('success') else '连接测试失败',
                'output': result.get('data'),
                'error': result.get('message') if not result.get('success') else None
            }
        except Exception as e:
            return {'success': False, 'message': str(e)}

    @staticmethod
    def call_agent(agent_id, query, input_payload=None):
        """
        调用 Agent

        Args:
            agent_id: Agent ID
            query: 字符串输入（向后兼容）
            input_payload: 结构化输入（dict），可包含：
                - turns: 多轮对话历史
                - expected_tool_calls: 预期工具调用
                - context: 检索上下文
                - files: 文件引用
                - metadata: 其他元数据

        Returns:
            dict: {
                'success': bool,
                'data': 原始回答（字符串，保证向后兼容）
                'payload': 结构化输出（可包含 answer, tool_calls, trace, files 等）
                'message': 错误信息（仅失败时）
            }
        """
        try:
            agent = Agent.query.get(agent_id)
            if not agent:
                return {'success': False, 'message': 'Agent不存在'}

            if not agent.is_active:
                return {'success': False, 'message': 'Agent未激活'}

            if agent.access_type == 'script':
                return AgentService._call_script_agent(agent, query, input_payload)
            elif agent.access_type == 'api':
                return AgentService._call_api_agent(agent, query, input_payload)
            elif agent.access_type == 'local':
                return AgentService._call_local_agent(agent, query, input_payload)
            else:
                return {'success': False, 'message': '不支持的Agent类型'}
        except Exception as e:
            return {'success': False, 'message': str(e)}

    @staticmethod
    def _call_script_agent(agent, query, input_payload=None):
        """通过脚本方式调用Agent"""
        try:
            if not agent.script_file:
                return {'success': False, 'message': '未上传脚本文件'}

            script_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                AgentService.UPLOAD_FOLDER,
                agent.script_file
            )

            if not os.path.exists(script_path):
                return {'success': False, 'message': '脚本文件不存在'}

            # 动态加载模块
            spec = importlib.util.spec_from_file_location(f"agent_module_{agent.id}", script_path)
            if not spec or not spec.loader:
                return {'success': False, 'message': '无法加载脚本模块'}

            agent_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(agent_module)

            # 调用入口函数：签名支持 func(query) 或 func(query, input_payload)
            entry_func = agent.entry_function or 'run_agent'
            if not hasattr(agent_module, entry_func):
                return {'success': False, 'message': f'脚本缺少入口函数: {entry_func}'}

            func = getattr(agent_module, entry_func)
            import inspect
            sig = inspect.signature(func)
            if len(sig.parameters) >= 2 and input_payload is not None:
                result = func(query, input_payload)
            else:
                result = func(query)

            # 统一标准化返回格式：str(data) 保证兼容旧评分器；payload 存结构化结果
            payload = result if isinstance(result, dict) else None
            return {
                'success': True,
                'data': str(result.get('answer') if (isinstance(result, dict) and 'answer' in result) else result),
                'payload': payload
            }
        except Exception as e:
            return {'success': False, 'message': f'脚本调用失败: {str(e)}'}

    @staticmethod
    def _resolve_api_timeout(agent) -> float:
        """解析 API agent 的请求超时（秒）。

        优先级：access_config.timeout（agent 自定义）→ 环境变量 AGENT_API_TIMEOUT → 默认 120 秒。
        多步规划/工具调用类 agent 可能需要较长时间，旧硬编码 30 秒容易导致评测时 Read timed out。
        """
        default = 120.0
        try:
            cfg = json.loads(agent.access_config) if agent.access_config else {}
            if isinstance(cfg, dict) and cfg.get('timeout') is not None:
                return max(1.0, float(cfg['timeout']))
        except (ValueError, TypeError):
            pass
        env_val = os.environ.get('AGENT_API_TIMEOUT')
        if env_val:
            try:
                return max(1.0, float(env_val))
            except ValueError:
                pass
        try:
            from app.config.config import Config
            cfg_val = Config.get_runtime_config().get('agent_api_timeout')
            if cfg_val:
                return max(1.0, float(cfg_val))
        except (ImportError, TypeError, ValueError):
            pass
        return default

    def _call_api_agent(agent, query, input_payload=None):
        """通过API方式调用Agent"""
        try:
            if not agent.api_endpoint:
                return {'success': False, 'message': '未配置API地址'}

            url = agent.api_endpoint
            method = agent.api_method or 'POST'
            timeout = AgentService._resolve_api_timeout(agent)

            # 构建请求头
            headers = {}
            if agent.api_headers:
                headers.update(agent.api_headers)

            # 构建请求体：{input_payload} / {query_with_payload} 占位符支持结构化传参
            if agent.api_request_mapping:
                # 使用自定义映射
                payload = {}
                for key, value in agent.api_request_mapping.items():
                    if value == '{query}':
                        payload[key] = query
                    elif value == '{input_payload}' and input_payload:
                        payload[key] = input_payload
                    elif value == '{query_with_payload}' and input_payload:
                        payload[key] = {'query': query, **input_payload}
                    else:
                        payload[key] = value
            else:
                # 默认格式：兼容同时传 query 和结构化输入
                payload = {'query': query}
                if input_payload:
                    payload['input_payload'] = input_payload

            # 发送请求
            if method.upper() == 'GET':
                response = requests.get(url, params=payload, headers=headers, timeout=timeout)
            else:
                response = requests.post(url, json=payload, headers=headers, timeout=timeout)

            response.raise_for_status()
            response_data = response.json()

            # 处理响应映射
            if agent.api_response_mapping:
                result_path = agent.api_response_mapping.get('result_path', '')
                if result_path:
                    for key in result_path.split('.'):
                        if isinstance(response_data, dict) and key in response_data:
                            response_data = response_data[key]
                        else:
                            break

            # 标准化返回格式
            payload_data = response_data if isinstance(response_data, dict) else None
            return {
                'success': True,
                'data': str(response_data.get('answer') if (isinstance(response_data, dict) and 'answer' in response_data) else response_data),
                'payload': payload_data
            }
        except requests.exceptions.Timeout:
            return {
                'success': False,
                'message': f'API调用超时: Agent 在 {timeout} 秒内未返回完整结果。'
                           f'若 agent 需要更长处理时间，可在其 access_config 中设置 "timeout"（秒）'
                           f'或设置环境变量 AGENT_API_TIMEOUT 调大超时。'
            }
        except Exception as e:
            return {'success': False, 'message': f'API调用失败: {str(e)}'}

    @staticmethod
    def _call_local_agent(agent, query, input_payload=None):
        """调用本地模块中的Agent"""
        try:
            config = json.loads(agent.access_config) if agent.access_config else {}
            module_name = config.get('module')
            function_name = config.get('function', agent.entry_function)

            if not module_name:
                return {'success': False, 'message': '未配置模块名'}

            if module_name not in sys.modules:
                module = __import__(module_name)
            else:
                module = sys.modules[module_name]

            func = getattr(module, function_name)
            import inspect
            sig = inspect.signature(func)
            if len(sig.parameters) >= 2 and input_payload is not None:
                result = func(query, input_payload)
            else:
                result = func(query)

            # 标准化返回格式
            payload_data = result if isinstance(result, dict) else None
            return {
                'success': True,
                'data': str(result.get('answer') if (isinstance(result, dict) and 'answer' in result) else result),
                'payload': payload_data
            }
        except Exception as e:
            return {'success': False, 'message': str(e)}
