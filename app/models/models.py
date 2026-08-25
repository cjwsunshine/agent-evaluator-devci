from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(100), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='user')  # admin/user
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    test_cases = db.relationship('TestCase', backref='user', lazy=True)
    evaluation_sets = db.relationship('EvaluationSet', backref='user', lazy=True)
    tasks = db.relationship('EvaluationTask', backref='user', lazy=True, cascade='all, delete-orphan')

class TestCase(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    agent_id = db.Column(db.Integer, db.ForeignKey('agent.id'), nullable=True)
    name = db.Column(db.String(200), nullable=False)
    query = db.Column(db.Text, nullable=False)
    expected = db.Column(db.Text, nullable=False)
    tags = db.Column(db.String(200), nullable=True)
    evaluation_tool = db.Column(db.String(50), nullable=False, default='deepeval')
    metric = db.Column(db.String(100), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    # 结构化输入/输出：多轮对话、工具调用预期、检索上下文、文件信息等
    # JSON schema 参考:
    #   input_payload: {"query": "原始问题", "turns": [...], "expected_tool_calls": [...], "context": "..."
    #   expected_payload: {"answer": "预期回答", "tool_calls": [...], "context_relevance": [...]}
    input_payload = db.Column(db.JSON, nullable=True)
    expected_payload = db.Column(db.JSON, nullable=True)

    task_cases = db.relationship('TaskTestCase', backref='test_case', lazy=True, cascade='all, delete-orphan')
    set_id = db.Column(db.Integer, db.ForeignKey('evaluation_set.id'), nullable=True)

class EvaluationSet(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    agent_id = db.Column(db.Integer, db.ForeignKey('agent.id'), nullable=True)
    name = db.Column(db.String(200), nullable=False)
    evaluation_tool = db.Column(db.String(50), nullable=False, default='deepeval')
    status = db.Column(db.String(20), nullable=False, default='pending')  # pending/running/completed
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    test_cases = db.relationship('TestCase', backref='evaluation_set', lazy=True)

class Agent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    version = db.Column(db.String(50), nullable=False)
    access_type = db.Column(db.String(20), nullable=False, default='script')  # script/api/local
    script_file = db.Column(db.String(255), nullable=True)  # 上传的脚本文件路径
    entry_function = db.Column(db.String(100), nullable=False, default='run_agent')  # 入口函数名
    api_endpoint = db.Column(db.String(255), nullable=True)  # API接入地址
    api_method = db.Column(db.String(10), nullable=False, default='POST')
    api_headers = db.Column(db.JSON, nullable=True)  # API请求头配置
    api_request_mapping = db.Column(db.JSON, nullable=True)  # 请求参数映射
    api_response_mapping = db.Column(db.JSON, nullable=True)  # 响应结果映射
    access_config = db.Column(db.Text, nullable=True)  # JSON格式配置（兼容旧字段）
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    tasks = db.relationship('EvaluationTask', backref='agent', lazy=True, cascade='all, delete-orphan')
    test_cases = db.relationship('TestCase', backref='agent', lazy=True)
    evaluation_sets = db.relationship('EvaluationSet', backref='agent', lazy=True)

class EvaluationTask(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    agent_id = db.Column(db.Integer, db.ForeignKey('agent.id'), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    tools = db.Column(db.String(200), nullable=True)  # 逗号分隔的工具列表
    evaluation_tool = db.Column(db.String(50), nullable=False, default='deepeval')  # deepeval/promptfoo/trulens
    selected_metrics = db.Column(db.JSON, nullable=True)  # 选中的评测指标
    tool_config = db.Column(db.JSON, nullable=True)  # 评测工具特定配置
    mode = db.Column(db.String(20), nullable=False, default='batch')  # batch/incremental
    priority = db.Column(db.String(10), nullable=False, default='medium')  # high/medium/low
    status = db.Column(db.String(20), nullable=False, default='pending')  # pending/running/completed/failed
    total_cases = db.Column(db.Integer, nullable=False, default=0)
    completed_cases = db.Column(db.Integer, nullable=False, default=0)
    start_time = db.Column(db.DateTime, nullable=True)
    end_time = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    task_cases = db.relationship('TaskTestCase', backref='task', lazy=True, cascade='all, delete-orphan')

class TaskTestCase(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey('evaluation_task.id'), nullable=False)
    test_case_id = db.Column(db.Integer, db.ForeignKey('test_case.id'), nullable=False)
    agent_output = db.Column(db.Text, nullable=True)
    # 结构化 agent 输出：tool_calls, trace, files, token 消耗, 耗时等
    agent_output_payload = db.Column(db.JSON, nullable=True)
    # agent 调用耗时（毫秒），由平台在评测时用 perf_counter 实测
    latency_ms = db.Column(db.Float, nullable=True)
    status = db.Column(db.String(20), nullable=False, default='pending')  # pending/running/passed/failed
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    results = db.relationship('EvaluationResult', backref='task_case', lazy=True, cascade='all, delete-orphan')

class EvaluationResult(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    task_case_id = db.Column(db.Integer, db.ForeignKey('task_test_case.id'), nullable=False)
    tool_name = db.Column(db.String(50), nullable=False)
    score = db.Column(db.Float, nullable=True)
    status = db.Column(db.String(20), nullable=False)  # passed/failed
    error_message = db.Column(db.Text, nullable=True)
    detailed_log = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class SystemLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    action = db.Column(db.String(100), nullable=False)
    content = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
