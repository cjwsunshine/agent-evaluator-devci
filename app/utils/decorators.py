from functools import wraps
from flask import request, jsonify
import jwt
from app.config.config import Config

def auth_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        token = request.headers.get('Authorization')
        if not token:
            return jsonify({'success': False, 'message': '缺少认证令牌'}), 401
        if token.lower().startswith('bearer '):
            token = token[7:].strip()

        try:
            payload = jwt.decode(token, Config.JWT_SECRET_KEY, algorithms=['HS256'])
            request.environ['X-User-Id'] = str(payload['user_id'])
            request.environ['X-User-Role'] = payload['role']
        except jwt.ExpiredSignatureError:
            return jsonify({'success': False, 'message': '令牌已过期'}), 401
        except jwt.InvalidTokenError:
            return jsonify({'success': False, 'message': '无效的令牌'}), 401
        
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        role = request.environ.get('X-User-Role')
        if role != 'admin':
            return jsonify({'success': False, 'message': '权限不足'}), 403
        
        return f(*args, **kwargs)
    return decorated_function
