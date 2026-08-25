import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from app import create_app
from app.models.models import Agent, EvaluationTask, TaskTestCase, TestCase, db
from app.services.evaluation_engine import PromptfooEvaluator


def main():
    app = create_app()
    with app.app_context():
        agent = db.session.query(Agent).filter_by(is_active=True).first()
        print('agent', agent.id if agent else None, agent.name if agent else None)
        if not agent:
            return

        task = EvaluationTask(
            user_id=agent.user_id,
            agent_id=agent.id,
            name='promptfoo smoke',
            evaluation_tool='promptfoo',
            tools='promptfoo',
            total_cases=1,
            status='running'
        )
        db.session.add(task)
        db.session.flush()

        case = db.session.query(TestCase).filter_by(user_id=agent.user_id).first()
        if not case:
            case = TestCase(
                user_id=agent.user_id,
                agent_id=agent.id,
                name='smoke',
                query='你好',
                expected='你好',
                evaluation_tool='promptfoo',
                metric='contains'
            )
            db.session.add(case)
            db.session.flush()

        task_case = TaskTestCase(task_id=task.id, test_case_id=case.id)
        db.session.add(task_case)
        db.session.commit()

        result = PromptfooEvaluator(task).evaluate()
        print(result)


if __name__ == '__main__':
    main()
