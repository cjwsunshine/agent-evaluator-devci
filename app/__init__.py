from flask import Flask, render_template
from flask_cors import CORS
from app.config.config import config
from app.models.models import db
from sqlalchemy import inspect, text


def _ensure_test_case_columns():
    columns = {column['name'] for column in inspect(db.engine).get_columns('test_case')}
    if 'agent_id' not in columns:
        db.session.execute(text("ALTER TABLE test_case ADD COLUMN agent_id INTEGER"))
    if 'set_id' not in columns:
        db.session.execute(text("ALTER TABLE test_case ADD COLUMN set_id INTEGER"))
    if 'evaluation_tool' not in columns:
        db.session.execute(text("ALTER TABLE test_case ADD COLUMN evaluation_tool VARCHAR(50) NOT NULL DEFAULT 'deepeval'"))
    if 'metric' not in columns:
        db.session.execute(text("ALTER TABLE test_case ADD COLUMN metric VARCHAR(100)"))
    db.session.commit()


def _ensure_task_test_case_columns():
    columns = {column['name'] for column in inspect(db.engine).get_columns('task_test_case')}
    if 'latency_ms' not in columns:
        db.session.execute(text("ALTER TABLE task_test_case ADD COLUMN latency_ms FLOAT"))
    db.session.commit()


def create_app(config_name='default'):
    import os
    import time
    template_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'templates')
    static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'static')
    app = Flask(__name__, template_folder=template_dir, static_folder=static_dir)
    app.config.from_object(config[config_name])

    # 静态资源版本号：应用启动时间戳。模板用 ?v={{ static_version() }} 强制浏览器拉取最新 JS/CSS，避免缓存旧版本。
    _static_version = str(int(time.time()))

    @app.template_global()
    def static_version():
        return _static_version


    # 初始化数据库
    db.init_app(app)

    # 启用CORS
    CORS(app)

    # 创建数据库表
    with app.app_context():
        db.create_all()
        _ensure_test_case_columns()
        _ensure_task_test_case_columns()

    # 注册蓝图
    from app.api.routes import api_bp
    app.register_blueprint(api_bp, url_prefix='/api')

    # 前端页面路由
    @app.route('/')
    @app.route('/index')
    def index():
        return render_template('index.html')

    @app.route('/login')
    def login():
        return render_template('login.html')

    @app.route('/pipeline/report/<path:run_id>')
    def pipeline_report(run_id):
        """Serve a generated pipeline HTML report from eval_output/<run_id>/."""
        from flask import send_from_directory, abort
        report_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), '..', 'eval_output', run_id
        )
        if not os.path.isfile(os.path.join(report_dir, 'report.html')):
            abort(404)
        return send_from_directory(report_dir, 'report.html')

    return app