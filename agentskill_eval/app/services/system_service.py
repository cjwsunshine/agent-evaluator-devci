import os
import json
from app.config.config import Config

class SystemService:
    @staticmethod
    def get_config():
        try:
            config = {
                'promptfoo_path': Config.PROMPTFOO_PATH,
                'depeval_path': Config.DEEPEVAL_PATH,
                'trulens_path': Config.TRULENS_PATH,
                'max_concurrent_tasks': Config.MAX_CONCURRENT_TASKS,
                'max_test_cases_per_task': Config.MAX_TEST_CASES_PER_TASK,
                'test_case_timeout': Config.TEST_CASE_TIMEOUT
            }
            return {'success': True, 'data': config}
        except Exception as e:
            return {'success': False, 'message': str(e)}
    
    @staticmethod
    def update_config(data):
        try:
            # 这里可以实现配置更新逻辑
            # 例如更新环境变量或配置文件
            return {'success': True, 'message': '配置更新成功'}
        except Exception as e:
            return {'success': False, 'message': str(e)}