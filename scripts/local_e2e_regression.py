import os
import sys
import time

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from app import create_app
from app.models.models import Agent, EvaluationResult, EvaluationSet, EvaluationTask, TaskTestCase, TestCase, User, db
from app.services.report_service import ReportService
from app.services.task_service import TaskService
from app.services.test_case_service import TestCaseService


def wait_for_task(user_id, task_id, timeout_seconds=30):
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        status = TaskService.get_task_status(user_id, task_id)
        if not status.get('success'):
            return status
        task_status = status['data']['status']
        if task_status in {'completed', 'failed', 'stopped'}:
            return status
        time.sleep(0.5)
    return {'success': False, 'message': '任务等待超时'}


def cleanup_created_entities(user_id, task_id=None, set_id=None):
    if task_id:
        task = db.session.get(EvaluationTask, task_id)
        if task and task.user_id == user_id:
            db.session.delete(task)
    if set_id:
        evaluation_set = db.session.get(EvaluationSet, set_id)
        if evaluation_set and evaluation_set.user_id == user_id:
            db.session.delete(evaluation_set)
    db.session.commit()


def main():
    app = create_app()
    with app.app_context():
        user = db.session.query(User).first()
        agent = db.session.query(Agent).filter_by(is_active=True).first()
        if not user or not agent:
            print({'success': False, 'message': '缺少可用用户或Agent'})
            return

        created_set_id = None
        created_task_id = None

        try:
            set_result = TestCaseService.create_evaluation_set(user.id, {
                'name': 'E2E 回归评测集',
                'agent_id': agent.id,
                'evaluation_tool': 'promptfoo',
                'metric': 'contains',
                'test_cases': [
                    {
                        'name': '回归问候',
                        'query': '你好',
                        'expected': '你好',
                        'tags': 'e2e,promptfoo',
                        'metric': 'contains'
                    }
                ]
            })
            print('create_evaluation_set', set_result)
            if not set_result.get('success'):
                return

            created_set_id = set_result['data']['id']
            evaluation_set = db.session.get(EvaluationSet, created_set_id)
            case_ids = [case.id for case in evaluation_set.test_cases]

            task_result = TaskService.create_task(user.id, {
                'name': 'E2E 回归任务',
                'agent_id': agent.id,
                'evaluation_tool': 'promptfoo',
                'tools': ['promptfoo'],
                'test_cases': case_ids,
                'selected_metrics': ['contains']
            })
            print('create_task', task_result)
            if not task_result.get('success'):
                return

            created_task_id = task_result['data']['id']

            start_result = TaskService.start_task(user.id, created_task_id)
            print('start_task', start_result)
            if not start_result.get('success'):
                return

            status_result = wait_for_task(user.id, created_task_id)
            print('task_status', status_result)

            report_result = ReportService.generate_report(user.id, created_task_id)
            print('report', report_result)

            task = db.session.get(EvaluationTask, created_task_id)
            task_cases = db.session.query(TaskTestCase).filter_by(task_id=created_task_id).count()
            results = db.session.query(EvaluationResult).join(TaskTestCase).filter(TaskTestCase.task_id == created_task_id).count()
            print({
                'task_status': task.status if task else None,
                'task_cases': task_cases,
                'results': results
            })
        finally:
            cleanup_created_entities(user.id, created_task_id, created_set_id)


if __name__ == '__main__':
    main()
