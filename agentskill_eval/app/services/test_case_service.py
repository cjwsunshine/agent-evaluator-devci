from app.models.models import db, TestCase

class TestCaseService:
    @staticmethod
    def get_test_cases(user_id):
        try:
            test_cases = TestCase.query.filter_by(user_id=user_id).all()
            result = []
            for case in test_cases:
                result.append({
                    'id': case.id,
                    'name': case.name,
                    'query': case.query,
                    'expected': case.expected,
                    'tags': case.tags,
                    'created_at': case.created_at.isoformat()
                })
            return {'success': True, 'data': result}
        except Exception as e:
            return {'success': False, 'message': str(e)}
    
    @staticmethod
    def create_test_case(user_id, data):
        try:
            test_case = TestCase(
                user_id=user_id,
                name=data.get('name'),
                query=data.get('query'),
                expected=data.get('expected'),
                tags=data.get('tags')
            )
            db.session.add(test_case)
            db.session.commit()
            return {'success': True, 'message': '测试用例创建成功', 'data': {'id': test_case.id}}
        except Exception as e:
            db.session.rollback()
            return {'success': False, 'message': str(e)}
    
    @staticmethod
    def update_test_case(user_id, case_id, data):
        try:
            test_case = TestCase.query.filter_by(id=case_id, user_id=user_id).first()
            if not test_case:
                return {'success': False, 'message': '测试用例不存在'}
            
            test_case.name = data.get('name', test_case.name)
            test_case.query = data.get('query', test_case.query)
            test_case.expected = data.get('expected', test_case.expected)
            test_case.tags = data.get('tags', test_case.tags)
            
            db.session.commit()
            return {'success': True, 'message': '测试用例更新成功'}
        except Exception as e:
            db.session.rollback()
            return {'success': False, 'message': str(e)}
    
    @staticmethod
    def delete_test_case(user_id, case_id):
        try:
            test_case = TestCase.query.filter_by(id=case_id, user_id=user_id).first()
            if not test_case:
                return {'success': False, 'message': '测试用例不存在'}
            
            db.session.delete(test_case)
            db.session.commit()
            return {'success': True, 'message': '测试用例删除成功'}
        except Exception as e:
            db.session.rollback()
            return {'success': False, 'message': str(e)}