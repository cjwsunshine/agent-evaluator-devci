from flask import Flask, render_template
from flask_cors import CORS
from app.config.config import config
from app.models.models import db

def create_app(config_name='default'):
    import os
    template_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'templates')
    static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'static')
    app = Flask(__name__, template_folder=template_dir, static_folder=static_dir)
    app.config.from_object(config[config_name])

    # 初始化数据库
    db.init_app(app)

    # 启用CORS
    CORS(app)

    # 创建数据库表
    with app.app_context():
        db.create_all()

    # 注册蓝图
    from app.api.routes import api_bp
    app.register_blueprint(api_bp, url_prefix='/api')

    # 前端页面路由
    @app.route('/')
    def index():
        return render_template('index.html')

    @app.route('/login')
    def login():
        return render_template('login.html')

    return app