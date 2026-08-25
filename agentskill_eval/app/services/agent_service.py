from app.models.models import db, Agent
import json
import requests
import importlib.util
import os

class AgentService:
    @staticmethod
    def get_agents(user_id):
        try:
            agents = Agent.query.filter_by(user_id=user_id).all()
            result = []
            for agent in agents:
                config = json.loads(agent.access_config) if agent.access_config else {}
                result.append({
                    'id': agent.id,
                    'name': agent.name,
                    'version': agent.version,
                    'endpoint': config.get('endpoint', ''),
                    'apiKey': config.get('apiKey', ''),
                    'status': config.get('status', 'active'),
                    'access_type': agent.access_type,
                    'created_at': agent.created_at.isoformat()
                })
            return {'success': True, 'data': result}
        except Exception as e:
            return {'success': False, 'message': str(e)}

    @staticmethod
    def create_agent(user_id, data):
        try:
            config = {
                'endpoint': data.get('endpoint', ''),
                'apiKey': data.get('apiKey', ''),
                'status': 'active'
            }
            agent = Agent(
                user_id=user_id,
                name=data.get('name'),
                version=data.get('version'),
                access_type=data.get('access_type', 'api'),
                access_config=json.dumps(config)
            )
            db.session.add(agent)
            db.session.commit()
            return {'success': True, 'message': 'Agent创建成功', 'data': {'id': agent.id}}
        except Exception as e:
            db.session.rollback()
            return {'success': False, 'message': str(e)}

    @staticmethod
    def update_agent(user_id, agent_id, data):
        try:
            agent = Agent.query.filter_by(id=agent_id, user_id=user_id).first()
            if not agent:
                return {'success': False, 'message': 'Agent不存在'}

            config = json.loads(agent.access_config) if agent.access_config else {}

            if 'name' in data:
                agent.name = data['name']
            if 'version' in data:
                agent.version = data['version']
            if 'endpoint' in data:
                config['endpoint'] = data['endpoint']
            if 'apiKey' in data:
                config['apiKey'] = data['apiKey']
            if 'status' in data:
                config['status'] = data['status']

            agent.access_config = json.dumps(config)
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

            db.session.delete(agent)
            db.session.commit()
            return {'success': True, 'message': 'Agent删除成功'}
        except Exception as e:
            db.session.rollback()
            return {'success': False, 'message': str(e)}

    @staticmethod
    def call_agent(agent_id, query):
        try:
            agent = Agent.query.get(agent_id)
            if not agent:
                return {'success': False, 'message': 'Agent不存在'}

            config = json.loads(agent.access_config)

            if agent.access_type == 'script':
                return AgentService._call_script_agent(config, query)
            elif agent.access_type == 'api':
                return AgentService._call_api_agent(config, query)
            elif agent.access_type == 'local':
                return AgentService._call_local_agent(config, query)
            else:
                return {'success': False, 'message': '不支持的Agent类型'}
        except Exception as e:
            return {'success': False, 'message': str(e)}

    @staticmethod
    def _call_script_agent(config, query):
        try:
            script_path = config.get('script_path')
            if not os.path.exists(script_path):
                return {'success': False, 'message': '脚本文件不存在'}

            spec = importlib.util.spec_from_file_location('agent_module', script_path)
            agent_module = importlib.util.spec_from_file_location(spec)
            spec.loader.exec_module(agent_module)

            if hasattr(agent_module, 'run'):
                result = agent_module.run(query)
                return {'success': True, 'data': result}
            else:
                return {'success': False, 'message': '脚本缺少run函数'}
        except Exception as e:
            return {'success': False, 'message': str(e)}

    @staticmethod
    def _call_api_agent(config, query):
        try:
            url = config.get('endpoint') or config.get('url')
            headers = config.get('headers', {})
            headers['Authorization'] = f"Bearer {config.get('apiKey', '')}"
            timeout = config.get('timeout', 30)

            payload = {
                'query': query
            }

            response = requests.post(url, json=payload, headers=headers, timeout=timeout)
            response.raise_for_status()

            return {'success': True, 'data': response.json()}
        except Exception as e:
            return {'success': False, 'message': str(e)}

    @staticmethod
    def _call_local_agent(config, query):
        try:
            module_name = config.get('module')
            function_name = config.get('function')

            module = __import__(module_name)
            func = getattr(module, function_name)

            result = func(query)
            return {'success': True, 'data': result}
        except Exception as e:
            return {'success': False, 'message': str(e)}