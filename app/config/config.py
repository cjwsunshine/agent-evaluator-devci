import json
import os
import sys
from dotenv import load_dotenv

# 加载项目根目录的 .env 文件
env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), '.env')
load_dotenv(dotenv_path=env_path)

class Config:
    # 系统基础配置
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key'
    JWT_SECRET_KEY = os.environ.get('JWT_SECRET_KEY') or SECRET_KEY
    # 使用绝对路径确保数据库位置固定
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    DEFAULT_DB_PATH = f'sqlite:///{os.path.join(BASE_DIR, "eval_platform.db")}'
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or DEFAULT_DB_PATH
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
    AGENT_API_TIMEOUT = 120  # 秒

    # RAGAS 专用配置（可选；留空则复用方舟 key/Base URL）
    RAGAS_API_KEY = os.environ.get('RAGAS_API_KEY') or ''
    RAGAS_BASE_URL = os.environ.get('RAGAS_BASE_URL') or ''
    RAGAS_MODEL = os.environ.get('RAGAS_MODEL') or ''
    RAGAS_EMBEDDING_MODEL = os.environ.get('RAGAS_EMBEDDING_MODEL') or os.environ.get('ARK_EMBEDDING_MODEL') or ''
    RAGAS_EMBEDDING_BASE_URL = os.environ.get('RAGAS_EMBEDDING_BASE_URL') or os.environ.get('ARK_EMBEDDING_BASE_URL') or ''
    RAGAS_TIMEOUT_SECONDS = 90

    # PikoCI 编排引擎连接配置
    PIKOCI_URL = os.environ.get('PIKOCI_URL') or 'http://localhost:8080'
    PIKOCI_TEAM = os.environ.get('PIKOCI_TEAM') or 'main'
    PIKOCI_PIPELINE = os.environ.get('PIKOCI_PIPELINE') or 'agent-eval'
    PIKOCI_JOB = os.environ.get('PIKOCI_JOB') or 'evaluate'
    PIKOCI_USER = os.environ.get('PIKOCI_USER') or 'admin'
    PIKOCI_PASS = os.environ.get('PIKOCI_PASS') or 'admin123'

    # 视为敏感信息的配置键：GET 时不回传明文，仅回传是否已配置
    SECRET_CONFIG_KEYS = frozenset({
        'ark_api_key', 'ragas_api_key', 'openai_api_key',
        'pikoci_pass', 'secret_key',
    })

    # 必须为整数的配置键
    INT_CONFIG_KEYS = frozenset({
        'max_concurrent_tasks', 'max_test_cases_per_task',
        'test_case_timeout', 'agent_api_timeout', 'ragas_timeout_seconds',
    })
    
    # 上传文件配置
    UPLOAD_FOLDER = 'uploads'
    AGENTS_UPLOAD_FOLDER = 'agents_uploads'
    TEST_CASES_UPLOAD_FOLDER = 'test_cases_uploads'
    RESULTS_FOLDER = 'results'
    ALLOWED_EXTENSIONS = {'py', 'json', 'yaml', 'yml', 'csv'}
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB

    # 火山方舟（Ark）/模型运行配置
    RUNTIME_CONFIG_PATH = os.path.join(BASE_DIR, 'instance', 'system_config.json')
    ARK_API_KEY = os.environ.get('ARK_API_KEY') or ''
    ARK_BASE_URL = os.environ.get('ARK_BASE_URL') or 'https://ark.cn-beijing.volces.com/api/coding/v3'
    ARK_MODEL = os.environ.get('ARK_MODEL') or 'deepseek-v4-pro'

    @classmethod
    def get_runtime_config(cls):
        data = {}
        if os.path.exists(cls.RUNTIME_CONFIG_PATH):
            with open(cls.RUNTIME_CONFIG_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)

        def pick(key, default):
            # 页面保存值（data）优先，其次环境变量，最后代码默认值
            return data.get(key) if data.get(key) not in (None, '') else default

        def pick_int(key, default):
            raw = data.get(key)
            if raw in (None, ''):
                return default
            try:
                return int(raw)
            except (TypeError, ValueError):
                return default

        return {
            # —— 评测引擎路径 ——
            'promptfoo_path': pick('promptfoo_path', cls.PROMPTFOO_PATH),
            'promptfoo_results': pick('promptfoo_results', os.path.join(cls.BASE_DIR, 'results', 'promptfoo')),
            'deepeval_path': pick('deepeval_path', cls.DEEPEVAL_PATH),
            'trulens_path': pick('trulens_path', cls.TRULENS_PATH),
            # —— 火山方舟（Ark）/模型 ——
            'ark_api_key': pick('ark_api_key', cls.ARK_API_KEY),
            'ark_base_url': pick('ark_base_url', cls.ARK_BASE_URL),
            'execution_model': pick('execution_model', cls.ARK_MODEL),
            'evaluation_model': pick('evaluation_model', pick('execution_model', cls.ARK_MODEL)),
            'openai_api_key': pick('openai_api_key', cls.OPENAI_API_KEY),
            # —— RAGAS 专用 ——
            'ragas_api_key': pick('ragas_api_key', cls.RAGAS_API_KEY),
            'ragas_base_url': pick('ragas_base_url', cls.RAGAS_BASE_URL),
            'ragas_model': pick('ragas_model', cls.RAGAS_MODEL),
            'ragas_embedding_model': pick('ragas_embedding_model', cls.RAGAS_EMBEDDING_MODEL),
            'ragas_embedding_base_url': pick('ragas_embedding_base_url', cls.RAGAS_EMBEDDING_BASE_URL),
            'ragas_timeout_seconds': pick_int('ragas_timeout_seconds', cls.RAGAS_TIMEOUT_SECONDS),
            # —— 运行参数 ——
            'max_concurrent_tasks': pick_int('max_concurrent_tasks', cls.MAX_CONCURRENT_TASKS),
            'max_test_cases_per_task': pick_int('max_test_cases_per_task', cls.MAX_TEST_CASES_PER_TASK),
            'test_case_timeout': pick_int('test_case_timeout', cls.TEST_CASE_TIMEOUT),
            'agent_api_timeout': pick_int('agent_api_timeout', cls.AGENT_API_TIMEOUT),
            # —— 日志 ——
            'log_level': pick('log_level', cls.LOG_LEVEL),
            'log_file': pick('log_file', cls.LOG_FILE),
            # —— PikoCI 连接 ——
            'pikoci_url': pick('pikoci_url', cls.PIKOCI_URL),
            'pikoci_team': pick('pikoci_team', cls.PIKOCI_TEAM),
            'pikoci_pipeline': pick('pikoci_pipeline', cls.PIKOCI_PIPELINE),
            'pikoci_job': pick('pikoci_job', cls.PIKOCI_JOB),
            'pikoci_user': pick('pikoci_user', cls.PIKOCI_USER),
            'pikoci_pass': pick('pikoci_pass', cls.PIKOCI_PASS),
        }

    @classmethod
    def get_public_runtime_config(cls):
        """返回可下发给页面的配置：敏感字段不回传明文，仅回传是否已配置。"""
        cfg = cls.get_runtime_config()
        masked = dict(cfg)
        for key in cls.SECRET_CONFIG_KEYS:
            if key in masked:
                value = masked.get(key)
                masked[key] = {
                    '_secret': True,
                    'configured': bool(value),
                    'placeholder': '已配置，留空保存则保持不变' if value else '未配置',
                }
        return masked

    @classmethod
    def update_runtime_config(cls, updates):
        config = cls.get_runtime_config()
        allowed_keys = set(config.keys())
        for key, value in updates.items():
            if key not in allowed_keys or value is None:
                continue
            # 敏感字段：空串 / 占位符表示"保持原值不变"，避免覆盖
            if key in cls.SECRET_CONFIG_KEYS:
                if isinstance(value, str):
                    stripped = value.strip()
                    if stripped == '' or stripped.startswith('__') or stripped == '********':
                        continue
                    config[key] = stripped
                continue
            if key in cls.INT_CONFIG_KEYS:
                if isinstance(value, str) and value.strip() == '':
                    continue
                try:
                    config[key] = int(value)
                except (TypeError, ValueError):
                    continue
                continue
            if isinstance(value, str):
                config[key] = value.strip()
            else:
                config[key] = value

        os.makedirs(os.path.dirname(cls.RUNTIME_CONFIG_PATH), exist_ok=True)
        with open(cls.RUNTIME_CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        return config

    @classmethod
    def resolve_promptfoo_command(cls, configured_path=None):
        candidate = (configured_path or '').strip()
        invalid_suffixes = ('.js', '.json', '.yaml', '.yml')
        if candidate and not candidate.endswith(invalid_suffixes):
            return candidate

        local_bin = os.path.join(cls.BASE_DIR, 'node_modules', '.bin', 'promptfoo')
        if os.path.exists(local_bin):
            return local_bin

        return 'promptfoo'

    @classmethod
    def resolve_python_command(cls):
        return sys.executable or 'python3'

class DevelopmentConfig(Config):
    DEBUG = True
    
class ProductionConfig(Config):
    DEBUG = False

config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig
}
