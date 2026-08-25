#!/usr/bin/env python3
"""
初始化管理员账户
运行方式: python3 init_admin.py
"""

import sys
sys.path.insert(0, '.')

from app import create_app
from app.models.models import db, User
from app.services.auth_service import AuthService

ADMIN_USERNAME = 'admin'
ADMIN_PASSWORD = 'admin123'

def init_admin():
    app = create_app()

    with app.app_context():
        # 检查管理员是否已存在
        admin = User.query.filter_by(username=ADMIN_USERNAME).first()

        if admin:
            print(f"⚠️  管理员账户 '{ADMIN_USERNAME}' 已存在")
            return

        # 创建管理员账户
        hashed_password = AuthService.hash_password(ADMIN_PASSWORD)
        admin = User(
            username=ADMIN_USERNAME,
            password=hashed_password,
            role='admin'
        )
        db.session.add(admin)
        db.session.commit()

        print(f"✅ 管理员账户创建成功！")
        print(f"   用户名: {ADMIN_USERNAME}")
        print(f"   密码: {ADMIN_PASSWORD}")
        print(f"   角色: admin")

if __name__ == '__main__':
    init_admin()
