from app.models.models import db, User
import jwt
import time
from werkzeug.security import check_password_hash, generate_password_hash
from app.config.config import Config

class AuthService:
    @staticmethod
    def hash_password(password):
        return generate_password_hash(password)

    @staticmethod
    def verify_password(stored_password, password):
        if not stored_password:
            return False

        if stored_password.startswith('pbkdf2:') or stored_password.startswith('scrypt:'):
            return check_password_hash(stored_password, password)

        # Backward compatibility for legacy SHA256-only passwords.
        import hashlib
        return stored_password == hashlib.sha256(password.encode()).hexdigest()
    
    @staticmethod
    def generate_token(user_id, role):
        payload = {
            'user_id': user_id,
            'role': role,
            'exp': time.time() + 86400  # 24小时过期
        }
        return jwt.encode(payload, Config.JWT_SECRET_KEY, algorithm='HS256')
    
    @staticmethod
    def register(data):
        try:
            username = data.get('username')
            password = data.get('password')
            role = 'user'

            if not username or not password:
                return {'success': False, 'message': '用户名和密码不能为空'}
            
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

            if not username or not password:
                return {'success': False, 'message': '用户名或密码错误'}
            
            user = User.query.filter_by(username=username).first()
            if not user:
                return {'success': False, 'message': '用户名或密码错误'}
            
            if not AuthService.verify_password(user.password, password):
                return {'success': False, 'message': '用户名或密码错误'}

            if not (user.password.startswith('pbkdf2:') or user.password.startswith('scrypt:')):
                user.password = AuthService.hash_password(password)
                db.session.commit()
            
            token = AuthService.generate_token(user.id, user.role)
            return {'success': True, 'message': '登录成功', 'token': token, 'user_id': user.id, 'role': user.role}
        except Exception as e:
            return {'success': False, 'message': str(e)}
