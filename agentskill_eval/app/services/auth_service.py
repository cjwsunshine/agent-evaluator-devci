from app.models.models import db, User
import hashlib
import jwt
import time

class AuthService:
    @staticmethod
    def hash_password(password):
        return hashlib.sha256(password.encode()).hexdigest()
    
    @staticmethod
    def generate_token(user_id, role):
        payload = {
            'user_id': user_id,
            'role': role,
            'exp': time.time() + 86400  # 24小时过期
        }
        return jwt.encode(payload, 'secret_key', algorithm='HS256')
    
    @staticmethod
    def register(data):
        try:
            username = data.get('username')
            password = data.get('password')
            role = data.get('role', 'user')
            
            if User.query.filter_by(username=username).first():
                return {'success': False, 'message': '用户名已存在'}
            
            hashed_password = AuthService.hash_password(password)
            user = User(username=username, password=hashed_password, role=role)
            db.session.add(user)
            db.session.commit()
            
            token = AuthService.generate_token(user.id, user.role)
            return {'success': True, 'message': '注册成功', 'token': token, 'user_id': user.id, 'role': user.role}
        except Exception as e:
            db.session.rollback()
            return {'success': False, 'message': str(e)}
    
    @staticmethod
    def login(data):
        try:
            username = data.get('username')
            password = data.get('password')
            
            user = User.query.filter_by(username=username).first()
            if not user:
                return {'success': False, 'message': '用户名或密码错误'}
            
            hashed_password = AuthService.hash_password(password)
            if user.password != hashed_password:
                return {'success': False, 'message': '用户名或密码错误'}
            
            token = AuthService.generate_token(user.id, user.role)
            return {'success': True, 'message': '登录成功', 'token': token, 'user_id': user.id, 'role': user.role}
        except Exception as e:
            return {'success': False, 'message': str(e)}