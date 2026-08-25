from app.models.models import db, EvaluationSet, EvaluationTask, TaskTestCase, TestCase, EvaluationResult
from app.services.evaluation_engine import EvaluationEngine
from app.utils.timeutil import iso_utc
from flask import current_app
import threading
from datetime import datetime

class TaskService:
    @staticmethod
    def _update_task_evaluation_sets(task, status):
        set_ids = {
            task_case.test_case.set_id
            for task_case in task.task_cases
            if task_case.test_case and task_case.test_case.set_id
        }
        for set_id in set_ids:
            evaluation_set = db.session.get(EvaluationSet, set_id)
            if evaluation_set:
                evaluation_set.status = status

    @staticmethod
    def get_tasks(user_id):
        try:
            tasks = EvaluationTask.query.filter_by(user_id=user_id).all()
            result = []
            for task in tasks:
                # 从关联的 test_case 聚合指标：同一任务通常各用例是同一指标，
                # 若混用则用逗号分隔展示。selected_metrics 字段作为兜底。
                case_metrics = sorted({
                    tc.test_case.metric
                    for tc in task.task_cases
                    if tc.test_case and tc.test_case.metric
                })
                if case_metrics:
                    metric = ','.join(case_metrics)
                elif isinstance(task.selected_metrics, list) and task.selected_metrics:
                    metric = ','.join(str(m) for m in task.selected_metrics)
                else:
                    metric = ''
                result.append({
                    'id': task.id,
                    'name': task.name,
                    'agent_id': task.agent_id,
                    'agent_name': task.agent.name if task.agent else None,
                    'evaluation_tool': task.evaluation_tool,
                    'metric': metric,
                    'status': task.status,
                    'tools': task.tools.split(',') if task.tools else [],
                    'total_cases': task.total_cases,
                    'completed_cases': task.completed_cases,
                    'created_at': iso_utc(task.created_at),
                    'updated_at': iso_utc(task.end_time or task.start_time or task.created_at)
                })
            # 按更新时间由新到旧排序
            result.sort(key=lambda item: item.get('updated_at') or item.get('created_at') or '', reverse=True)
            return {'success': True, 'data': result}
        except Exception as e:
            return {'success': False, 'message': str(e)}
    
    @staticmethod
    def create_task(user_id, data):
        try:
            test_cases = [int(case_id) for case_id in (data.get('test_cases') or data.get('testCaseIds') or [])]
            tools = [tool for tool in (data.get('tools') or ([data.get('evaluationTool')] if data.get('evaluationTool') else [])) if tool]
            agent_id = data.get('agent_id') or data.get('agentId')
            if not agent_id:
                return {'success': False, 'message': '请选择Agent后再创建评测任务'}
            if not test_cases:
                return {'success': False, 'message': '请选择测试用例后再创建评测任务'}

            # 运行前按每条用例的（工具, 指标）校验必填字段，避免用不合规的用例启动评测
            # （历史评测集可能在校验规则上线前已创建）。
            from app.services.test_case_service import TestCaseService
            case_records = db.session.query(TestCase).filter(TestCase.id.in_(test_cases)).all()
            run_errors = []
            for tc in case_records:
                item = {
                    'name': tc.name,
                    'query': tc.query,
                    'expected': tc.expected,
                    'input_payload': tc.input_payload,
                    'expected_payload': tc.expected_payload,
                }
                run_errors.extend(
                    TestCaseService.validate_test_cases_for_metric(
                        [item], tc.evaluation_tool or 'deepeval', tc.metric
                    )
                )
            if run_errors:
                return {
                    'success': False,
                    'message': '无法启动评测，测试项字段校验未通过：\n' + '\n'.join(f'· {e}' for e in run_errors)
                }

            normalized_tools = ','.join(sorted(tools))
            normalized_case_ids = sorted(test_cases)
            existing_tasks = EvaluationTask.query.filter_by(
                user_id=user_id,
                agent_id=agent_id,
                name=data.get('name'),
                evaluation_tool=data.get('evaluation_tool') or data.get('evaluationTool') or (tools[0] if tools else 'deepeval'),
                total_cases=len(test_cases)
            ).all()
            for existing_task in existing_tasks:
                existing_tools = ','.join(sorted(existing_task.tools.split(','))) if existing_task.tools else ''
                existing_case_ids = sorted(task_case.test_case_id for task_case in existing_task.task_cases)
                if existing_tools == normalized_tools and existing_case_ids == normalized_case_ids:
                    return {'success': True, 'message': '相同评测任务已存在', 'data': {'id': existing_task.id, 'duplicated': True}}

            task = EvaluationTask(
                user_id=user_id,
                agent_id=agent_id,
                name=data.get('name'),
                description=data.get('description'),
                tools=normalized_tools,
                evaluation_tool=data.get('evaluation_tool') or data.get('evaluationTool') or (tools[0] if tools else 'deepeval'),
                selected_metrics=data.get('selected_metrics') or data.get('selectedMetrics'),
                tool_config=data.get('tool_config') or data.get('promptfooConfig') or {},
                mode=data.get('mode', 'batch'),
                priority=data.get('priority', 'medium'),
                total_cases=len(test_cases)
            )
            db.session.add(task)
            db.session.flush()
            
            # 创建任务测试用例关联
            for case_id in test_cases:
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
    def _validate_task_cases(task_id):
        """按每条用例的（工具, 指标）校验必填字段，返回错误列表（空表示通过）。
        用于任务启动/重启前拦截历史遗留的不合规用例。"""
        from app.services.test_case_service import TestCaseService
        errors = []
        task_cases = TaskTestCase.query.filter_by(task_id=task_id).all()
        for task_case in task_cases:
            tc = task_case.test_case
            if not tc:
                continue
            item = {
                'name': tc.name,
                'query': tc.query,
                'expected': tc.expected,
                'input_payload': tc.input_payload,
                'expected_payload': tc.expected_payload,
            }
            errors.extend(
                TestCaseService.validate_test_cases_for_metric(
                    [item], tc.evaluation_tool or 'deepeval', tc.metric
                )
            )
        return errors

    @staticmethod
    def start_task(user_id, task_id):
        try:
            task = EvaluationTask.query.filter_by(id=task_id, user_id=user_id).first()
            if not task:
                return {'success': False, 'message': '任务不存在'}

            if task.status not in ('pending', 'running'):
                return {'success': False, 'message': '任务状态不正确'}

            run_errors = TaskService._validate_task_cases(task_id)
            if run_errors:
                return {'success': False, 'message': '无法启动评测，测试项字段校验未通过：\n' + '\n'.join(f'· {e}' for e in run_errors)}

            if task.status == 'running' and task.completed_cases == 0:
                TaskTestCase.query.filter_by(task_id=task_id, status='running').update({'status': 'pending'})

            task.status = 'running'
            task.start_time = datetime.utcnow()
            TaskService._update_task_evaluation_sets(task, 'running')
            db.session.commit()
            
            app = current_app._get_current_object()
            threading.Thread(target=TaskService._execute_task, args=(app, task_id), daemon=True).start()
            
            return {'success': True, 'message': '任务启动成功'}
        except Exception as e:
            db.session.rollback()
            return {'success': False, 'message': str(e)}
    
    @staticmethod
    def restart_task(user_id, task_id):
        try:
            task = EvaluationTask.query.filter_by(id=task_id, user_id=user_id).first()
            if not task:
                return {'success': False, 'message': '任务不存在'}

            task_cases = TaskTestCase.query.filter_by(task_id=task_id).all()
            if task.status == 'running':
                has_active_case = any(task_case.status in ('pending', 'running') for task_case in task_cases)
                if has_active_case and task.completed_cases < task.total_cases:
                    return {'success': False, 'message': '任务正在执行中，请稍后再重新启动'}

            run_errors = TaskService._validate_task_cases(task_id)
            if run_errors:
                return {'success': False, 'message': '无法重新启动评测，测试项字段校验未通过：\n' + '\n'.join(f'· {e}' for e in run_errors)}

            for task_case in task_cases:
                EvaluationResult.query.filter_by(task_case_id=task_case.id).delete()
                task_case.status = 'pending'
                task_case.agent_output = None

            task.status = 'running'
            task.completed_cases = 0
            task.start_time = datetime.utcnow()
            task.end_time = None
            TaskService._update_task_evaluation_sets(task, 'running')
            db.session.commit()

            app = current_app._get_current_object()
            threading.Thread(target=TaskService._execute_task, args=(app, task_id), daemon=True).start()

            return {'success': True, 'message': '任务重新启动成功'}
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
            TaskService._update_task_evaluation_sets(task, 'pending')
            db.session.commit()

            return {'success': True, 'message': '任务停止成功'}
        except Exception as e:
            db.session.rollback()
            return {'success': False, 'message': str(e)}

    @staticmethod
    def delete_task(user_id, task_id):
        try:
            task = EvaluationTask.query.filter_by(id=task_id, user_id=user_id).first()
            if not task:
                return {'success': False, 'message': '任务不存在'}

            if task.status == 'running':
                return {'success': False, 'message': '任务执行中，请先取消任务'}

            db.session.delete(task)
            db.session.commit()
            return {'success': True, 'message': '任务删除成功'}
        except Exception as e:
            db.session.rollback()
            return {'success': False, 'message': str(e)}

    @staticmethod
    def get_task_status(user_id, task_id):
        try:
            task = EvaluationTask.query.filter_by(id=task_id, user_id=user_id).first()
            if not task:
                return {'success': False, 'message': '任务不存在'}
            
            details = []
            task_cases = TaskTestCase.query.filter_by(task_id=task_id).all()
            for task_case in task_cases:
                test_case = db.session.get(TestCase, task_case.test_case_id)
                results = EvaluationResult.query.filter_by(task_case_id=task_case.id).all()
                details.append({
                    'id': task_case.id,
                    'name': test_case.name if test_case else f'测试项 {task_case.test_case_id}',
                    'query': test_case.query if test_case else '',
                    'expected': test_case.expected if test_case else '',
                    'agent_output': task_case.agent_output,
                    'evaluation_tool': test_case.evaluation_tool if test_case else task.evaluation_tool,
                    'status': task_case.status,
                    'created_at': iso_utc(task_case.created_at),
                    'results': [{
                        'tool_name': result.tool_name,
                        'score': result.score,
                        'status': result.status,
                        'error_message': result.error_message,
                        'detailed_log': result.detailed_log,
                        'created_at': iso_utc(result.created_at)
                    } for result in results]
                })

            return {
                'success': True,
                'data': {
                    'status': task.status,
                    'total_cases': task.total_cases,
                    'completed_cases': task.completed_cases,
                    'progress': f'{task.completed_cases}/{task.total_cases}',
                    'start_time': iso_utc(task.start_time),
                    'end_time': iso_utc(task.end_time),
                    'details': details
                }
            }
        except Exception as e:
            return {'success': False, 'message': str(e)}
    
    @staticmethod
    def _execute_task(app, task_id):
        with app.app_context():
            try:
                task = db.session.get(EvaluationTask, task_id)
                engine = EvaluationEngine(task_id)
                result = engine.run_evaluation()
                if not result.get('success'):
                    raise RuntimeError(result.get('error') or '评测执行失败')

                db.session.refresh(task)
                if task.status == 'running':
                    task.status = 'completed'
                    task.completed_cases = task.total_cases
                    task.end_time = datetime.utcnow()
                    TaskService._update_task_evaluation_sets(task, 'completed')
                    db.session.commit()
            except Exception as e:
                db.session.rollback()
                task = db.session.get(EvaluationTask, task_id)
                if task:
                    task.status = 'failed'
                    task.end_time = datetime.utcnow()
                    TaskService._update_task_evaluation_sets(task, 'failed')
                    db.session.commit()
