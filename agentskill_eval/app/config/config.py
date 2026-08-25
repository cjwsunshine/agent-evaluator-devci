import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # 系统基础配置
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key'
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or 'sqlite:///eval_platform.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # 评测工具配置
    PROMPTFOO_PATH = os.environ.get('PROMPTFOO_PATH') or 'promptfoo'
    DEEPEVAL_PATH = os.environ.get('DEEPEVAL_PATH') or 'depeval'
    TRULENS_PATH = os.environ.get('TRULENS_PATH') or 'trulens'
    
    # API密钥配置
    OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY') or ''
    
    # 日志配置
    LOG_LEVEL = os.environ.get('LOG_LEVEL') or 'INFO'
    LOG_FILE = os.environ.get('LOG_FILE') or 'app.log'
    
    # 任务配置
    MAX_CONCURRENT_TASKS = 3
    MAX_TEST_CASES_PER_TASK = 1000
    TEST_CASE_TIMEOUT = 5  # 秒
    
    # 上传文件配置
    UPLOAD_FOLDER = 'uploads'
    ALLOWED_EXTENSIONS = {'py', 'json', 'yaml', 'yml'}

class DevelopmentConfig(Config):
    DEBUG = True
    
class ProductionConfig(Config):
    DEBUG = False

config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig
}