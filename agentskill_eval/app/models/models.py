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
    tasks = db.relationship('EvaluationTask', backref='user', lazy=True)

class TestCase(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    query = db.Column(db.Text, nullable=False)
    expected = db.Column(db.Text, nullable=False)
    tags = db.Column(db.String(200), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    task_cases = db.relationship('TaskTestCase', backref='test_case', lazy=True)

class Agent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    version = db.Column(db.String(50), nullable=False)
    access_type = db.Column(db.String(20), nullable=False)  # script/api/local
    access_config = db.Column(db.Text, nullable=False)  # JSON格式配置
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    tasks = db.relationship('EvaluationTask', backref='agent', lazy=True)

class EvaluationTask(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    agent_id = db.Column(db.Integer, db.ForeignKey('agent.id'), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    tools = db.Column(db.String(200), nullable=False)  # 逗号分隔的工具列表
    tool_config = db.Column(db.Text, nullable=True)  # JSON格式配置
    mode = db.Column(db.String(20), nullable=False)  # batch/incremental
    priority = db.Column(db.String(10), nullable=False, default='medium')  # high/medium/low
    status = db.Column(db.String(20), nullable=False, default='pending')  # pending/running/completed/failed
    total_cases = db.Column(db.Integer, nullable=False, default=0)
    completed_cases = db.Column(db.Integer, nullable=False, default=0)
    start_time = db.Column(db.DateTime, nullable=True)
    end_time = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    task_cases = db.relationship('TaskTestCase', backref='task', lazy=True)

class TaskTestCase(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey('evaluation_task.id'), nullable=False)
    test_case_id = db.Column(db.Integer, db.ForeignKey('test_case.id'), nullable=False)
    agent_output = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), nullable=False, default='pending')  # pending/running/passed/failed
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    results = db.relationship('EvaluationResult', backref='task_case', lazy=True)

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