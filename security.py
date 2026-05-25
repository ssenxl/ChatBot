from functools import wraps
from flask import session, request, jsonify, redirect, url_for
import jwt
import datetime
import os
from powerbi_api_connector import PowerBIAPIConnector, create_auto_connector

# JWT Secret
JWT_SECRET = os.environ.get('JWT_SECRET', os.urandom(32))

def generate_token(user_id, email):
    """Generate JWT token"""
    payload = {
        'user_id': user_id,
        'email': email,
        'exp': datetime.datetime.utcnow() + datetime.timedelta(hours=24),
        'iat': datetime.datetime.utcnow()
    }
    return jwt.encode(payload, JWT_SECRET, algorithm='HS256')

def verify_token(token):
    """Verify JWT token"""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=['HS256'])
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None

def token_required(f):
    """Decorator for token authentication"""
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('Authorization')
        if not token:
            return jsonify({'success': False, 'message': 'Token is missing'}), 401
        
        if token.startswith('Bearer '):
            token = token[7:]
        
        payload = verify_token(token)
        if not payload:
            return jsonify({'success': False, 'message': 'Token is invalid or expired'}), 401
        
        return f(*args, **kwargs)
    return decorated

def rate_limit(max_requests=100, window=3600):
    """Simple rate limiting"""
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            # Store requests in session for simplicity
            if 'requests' not in session:
                session['requests'] = []
            
            now = datetime.datetime.now().timestamp()
            session['requests'] = [req for req in session['requests'] if now - req < window]
            
            if len(session['requests']) >= max_requests:
                return jsonify({'success': False, 'message': 'Rate limit exceeded'}), 429
            
            session['requests'].append(now)
            return f(*args, **kwargs)
        return decorated
    return decorator

def validate_powerbi_credentials(data):
    """Validate PowerBI credentials format"""
    required_fields = ['tenant_id', 'client_id', 'client_secret']
    
    for field in required_fields:
        if not data.get(field):
            return False, f'Missing {field}'
        
        # Basic format validation
        if field == 'tenant_id' and len(data[field]) < 10:
            return False, 'Invalid tenant ID format'
        elif field == 'client_id' and len(data[field]) < 10:
            return False, 'Invalid client ID format'
        elif field == 'client_secret' and len(data[field]) < 5:
            return False, 'Invalid client secret format'
    
    return True, 'Valid'

def sanitize_input(text):
    """Sanitize user input"""
    if not text:
        return ""
    
    # Remove potentially harmful characters
    dangerous_chars = ['<', '>', '"', "'", '&', 'script', 'javascript', 'onerror', 'onload']
    sanitized = text
    
    for char in dangerous_chars:
        sanitized = sanitized.replace(char, '')
    
    return sanitized.strip()[:1000]  # Limit length

def log_security_event(event_type, user_id, details):
    """Log security events"""
    log_entry = {
        'timestamp': datetime.datetime.utcnow().isoformat(),
        'event_type': event_type,
        'user_id': user_id,
        'ip_address': request.remote_addr,
        'user_agent': request.headers.get('User-Agent', ''),
        'details': details
    }
    
    # In production, use proper logging system
    print(f"SECURITY_LOG: {log_entry}")
