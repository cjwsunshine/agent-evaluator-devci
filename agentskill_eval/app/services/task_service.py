from app.models.models import db, EvaluationTask, TaskTestCase, TestCase
from app.services.agent_service import AgentService
from app.services.evaluation_engine import EvaluationEngine
import threading
import time
from datetime import datetime

class TaskService:
    @staticmethod
    def get_tasks(user_id):
        try:
            tasks = EvaluationTask.query.filter_by(user_id=user_id).all()
            result = []
            for task in tasks:
                result.append({
                    'id': task.id,
                    'name': task.name,
                    'status': task.status,
                    'tools': task.tools.split(','),
                    'total_cases': task.total_cases,
                    'completed_cases': task.completed_cases,
                    'created_at': task.created_at.isoformat()
                })
            return {'success': True, 'data': result}
        except Exception as e:
            return {'success': False, 'message': str(e)}
    
    @staticmethod
    def create_task(user_id, data):
        try:
            task = EvaluationTask(
                user_id=user_id,
                agent_id=data.get('agent_id'),
                name=data.get('name'),
                description=data.get('description'),
                tools=','.join(data.get('tools', [])),
                tool_config=data.get('tool_config', '{}'),
                mode=data.get('mode', 'batch'),
                priority=data.get('priority', 'medium'),
                total_cases=len(data.get('test_cases', []))
            )
            db.session.add(task)
            db.session.flush()
            
            # 创建任务测试用例关联
            for case_id in data.get('test_cases', []):
                task_case = TaskTestCase(
                    task_id=task.id,
                    test_case_id=case_id
                )
                db.session.add(task_case)
            
            db.session.commit()
            return {'success': True, 'message': '任务创建成功', 'data': {'id': task.id}}
        except Exception as e:
            db.session.rollback()
            return {'success': False, 'message': str(e)}
    
    @staticmethod
    def start_task(user_id, task_id):
        try:
            task = EvaluationTask.query.filter_by(id=task_id, user_id=user_id).first()
            if not task:
                return {'success': False, 'message': '任务不存在'}
            
            if task.status != 'pending':
                return {'success': False, 'message': '任务状态不正确'}
            
            task.status = 'running'
            task.start_time = datetime.utcnow()
            db.session.commit()
            
            # 启动异步执行
            threading.Thread(target=TaskService._execute_task, args=(task_id,)).start()
            
            return {'success': True, 'message': '任务启动成功'}
        except Exception as e:
            db.session.rollback()
            return {'success': False, 'message': str(e)}
    
    @staticmethod
    def stop_task(user_id, task_id):
        try:
            task = EvaluationTask.query.filter_by(id=task_id, user_id=user_id).first()
            if not task:
                return {'success': False, 'message': '任务不存在'}
            
            if task.status != 'running':
                return {'success': False, 'message': '任务状态不正确'}
            
            task.status = 'stopped'
            task.end_time = datetime.utcnow()
            db.session.commit()
            
            return {'success': True, 'message': '任务停止成功'}
        except Exception as e:
            db.session.rollback()
            return {'success': False, 'message': str(e)}
    
    @staticmethod
    def get_task_status(user_id, task_id):
        try:
            task = EvaluationTask.query.filter_by(id=task_id, user_id=user_id).first()
            if not task:
                return {'success': False, 'message': '任务不存在'}
            
            return {
                'success': True,
                'data': {
                    'status': task.status,
                    'total_cases': task.total_cases,
                    'completed_cases': task.completed_cases,
                    'progress': f'{task.completed_cases}/{task.total_cases}',
                    'start_time': task.start_time.isoformat() if task.start_time else None,
                    'end_time': task.end_time.isoformat() if task.end_time else None
                }
            }
        except Exception as e:
            return {'success': False, 'message': str(e)}
    
    @staticmethod
    def _execute_task(task_id):
        try:
            task = EvaluationTask.query.get(task_id)
            task_cases = TaskTestCase.query.filter_by(task_id=task_id).all()
            
            for task_case in task_cases:
                if task.status != 'running':
                    break
                
                task_case.status = 'running'
                db.session.commit()
                
                # 调用Agent
                test_case = TestCase.query.get(task_case.test_case_id)
                agent_result = AgentService.call_agent(task.agent_id, test_case.query)
                
                if agent_result['success']:
                    task_case.agent_output = str(agent_result['data'])
                    
                    # 执行评测
                    tools = task.tools.split(',')
                    for tool in tools:
                        eval_result = EvaluationEngine.evaluate(
                            tool, test_case, agent_result['data']
                        )
                        # 保存评测结果
                        # ...
                else:
                    task_case.status = 'failed'
                
                task_case.status = 'passed' if agent_result['success'] else 'failed'
                task.completed_cases += 1
                db.session.commit()
            
            task.status = 'completed'
            task.end_time = datetime.utcnow()
            db.session.commit()
        except Exception as e:
            task = EvaluationTask.query.get(task_id)
            if task:
                task.status = 'failed'
                task.end_time = datetime.utcnow()
                db.session.commit()