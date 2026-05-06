from flask import jsonify, request
from flask_login import login_required, current_user
from extensions import db
from models.user import User, Passkey
from utils import generate_passkey, get_utc_plus_8_time, get_settings, validate_username, validate_nickname
from datetime import timedelta
from . import auth_bp

@auth_bp.route('/api/users', methods=['GET', 'POST', 'PUT', 'DELETE'])
@login_required
def api_users():
    if not (current_user.is_admin or current_user.is_super_admin):
        return jsonify({'error': '权限不足'}), 403
    
    if request.method == 'GET':
        users = User.query.all()
        return jsonify([{
            'id': user.id,
            'username': user.username,
            'nickname': user.nickname,
            'display_name': user.display_name,
            'is_super_admin': user.is_super_admin,
            'is_admin': user.is_admin,
            'created_at': user.created_at.strftime('%Y-%m-%d %H:%M:%S')
        } for user in users])
    
    elif request.method == 'POST':
        data = request.json
        if not current_user.is_super_admin and data.get('is_admin'):
            return jsonify({'error': '只有超级管理员可以创建管理员用户'}), 403
        
        settings = get_settings()
        username_min = settings.get('username_manual_min', 3)
        username_max = settings.get('username_manual_max', 50)
        
        is_valid_username, username_error = validate_username(data['username'], username_min, username_max)
        if not is_valid_username:
            return jsonify({'error': username_error}), 400
        
        if User.query.filter_by(username=data['username']).first():
            return jsonify({'error': '用户名已存在'}), 400
        
        nickname = data.get('nickname')
        if nickname:
            allow_nickname = settings.get('allow_nickname', True)
            if not allow_nickname:
                return jsonify({'error': '系统已禁用昵称功能'}), 400
            
            nickname_min = settings.get('nickname_min_length', 2)
            nickname_max = settings.get('nickname_max_length', 20)
            is_valid_nickname, nickname_error = validate_nickname(nickname, nickname_min, nickname_max)
            if not is_valid_nickname:
                return jsonify({'error': nickname_error}), 400
        
        user = User(
            username=data['username'],
            nickname=nickname,
            is_admin=data.get('is_admin', False),
            is_super_admin=False
        )
        user.set_password(data['password'])
        db.session.add(user)
        db.session.commit()
        return jsonify({'id': user.id, 'username': user.username})
    
    elif request.method == 'PUT':
        data = request.json
        user = User.query.get(data['id'])
        if not user:
            return jsonify({'error': '用户不存在'}), 404
        
        if user.is_super_admin and user.id != current_user.id:
            return jsonify({'error': '超级管理员不可修改'}), 403
        
        if not current_user.is_super_admin and user.is_admin:
            return jsonify({'error': '只有超级管理员可以修改管理员用户'}), 403
        
        if 'password' in data and data['password']:
            user.set_password(data['password'])
        if 'is_admin' in data and current_user.is_super_admin and not user.is_super_admin:
            user.is_admin = data['is_admin']
        db.session.commit()
        return jsonify({'id': user.id, 'username': user.username})
    
    elif request.method == 'DELETE':
        user_id = request.json['id']
        user = User.query.get(user_id)
        if not user:
            return jsonify({'error': '用户不存在'}), 404
        
        if user.is_super_admin:
            return jsonify({'error': '超级管理员不可删除'}), 403
        
        if not current_user.is_super_admin and user.is_admin:
            return jsonify({'error': '只有超级管理员可以删除管理员用户'}), 403
        
        db.session.delete(user)
        db.session.commit()
        return jsonify({'success': True})

@auth_bp.route('/api/user/profile', methods=['GET', 'PUT'])
@login_required
def api_user_profile():
    settings = get_settings()
    
    if request.method == 'GET':
        return jsonify({
            'id': current_user.id,
            'username': current_user.username,
            'nickname': current_user.nickname,
            'display_name': current_user.display_name,
            'is_super_admin': current_user.is_super_admin,
            'is_admin': current_user.is_admin,
            'security_question': current_user.security_question,
            'allow_nickname': settings.get('allow_nickname', True),
            'nickname_min_length': settings.get('nickname_min_length', 2),
            'nickname_max_length': settings.get('nickname_max_length', 20),
            'allow_change_password': settings.get('allow_change_password', True),
            'allow_self_password_reset': settings.get('allow_self_password_reset', False)
        })
    
    elif request.method == 'PUT':
        data = request.json
        
        if 'nickname' in data:
            allow_nickname = settings.get('allow_nickname', True)
            if not allow_nickname:
                return jsonify({'error': '系统已禁用昵称功能'}), 400
            
            nickname = data['nickname'] if data['nickname'] else None
            if nickname:
                nickname_min = settings.get('nickname_min_length', 2)
                nickname_max = settings.get('nickname_max_length', 20)
                is_valid_nickname, nickname_error = validate_nickname(nickname, nickname_min, nickname_max)
                if not is_valid_nickname:
                    return jsonify({'error': nickname_error}), 400
            
            current_user.nickname = nickname
        
        if 'password' in data and data['password']:
            allow_change_password = settings.get('allow_change_password', True)
            if not allow_change_password and not current_user.is_super_admin:
                return jsonify({'error': '系统已禁用密码修改功能'}), 400
            
            password_strength = settings.get('password_strength', 1)
            allow_weak_password = settings.get('allow_weak_password', False)
            
            is_valid_password, password_error = validate_password_strength(data['password'], password_strength)
            if not is_valid_password:
                return jsonify({'error': password_error}), 400
            
            if not allow_weak_password and is_weak_password(data['password']):
                return jsonify({'error': '密码过于简单，请使用更强的密码'}), 400
            
            current_user.set_password(data['password'])
        
        if 'security_question' in data and 'security_answer' in data:
            allow_self_password_reset = settings.get('allow_self_password_reset', False)
            if not allow_self_password_reset:
                return jsonify({'error': '系统未启用安全问题功能'}), 400
            
            if data['security_question'] and data['security_answer']:
                current_user.security_question = data['security_question']
                current_user.set_security_answer(data['security_answer'])
            else:
                current_user.security_question = None
                current_user.security_answer_hash = None
        
        db.session.commit()
        return jsonify({'success': True, 'display_name': current_user.display_name})

@auth_bp.route('/api/passkeys', methods=['GET', 'POST', 'DELETE'])
@login_required
def api_passkeys():
    if not current_user.is_super_admin:
        return jsonify({'error': '权限不足'}), 403
    
    if request.method == 'GET':
        passkeys = Passkey.query.all()
        return jsonify([{
            'id': p.id,
            'key': p.key,
            'duration_days': p.duration_days,
            'max_uses': p.max_uses,
            'current_uses': p.current_uses,
            'created_at': p.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            'expires_at': p.expires_at.strftime('%Y-%m-%d %H:%M:%S') if p.expires_at else None,
            'is_active': p.is_active,
            'is_valid': p.is_valid()
        } for p in passkeys])
    
    elif request.method == 'POST':
        data = request.json
        duration_days = data.get('duration_days')
        max_uses = data.get('max_uses')
        
        key = generate_passkey()
        
        expires_at = None
        if duration_days:
            expires_at = get_utc_plus_8_time() + timedelta(days=duration_days)
        
        passkey = Passkey(
            key=key,
            duration_days=duration_days,
            max_uses=max_uses,
            expires_at=expires_at
        )
        db.session.add(passkey)
        db.session.commit()
        
        return jsonify({
            'id': passkey.id,
            'key': passkey.key,
            'duration_days': passkey.duration_days,
            'max_uses': passkey.max_uses,
            'current_uses': passkey.current_uses,
            'created_at': passkey.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            'expires_at': passkey.expires_at.strftime('%Y-%m-%d %H:%M:%S') if passkey.expires_at else None,
            'is_active': passkey.is_active
        })
    
    elif request.method == 'DELETE':
        passkey_id = request.json['id']
        passkey = Passkey.query.get(passkey_id)
        if not passkey:
            return jsonify({'error': 'Passkey不存在'}), 404
        
        db.session.delete(passkey)
        db.session.commit()
        return jsonify({'success': True})

@auth_bp.route('/api/auth/forgot-password/check', methods=['POST'])
def api_forgot_password_check():
    settings = get_settings()
    if not settings.get('allow_self_password_reset', False):
        return jsonify({'error': '自助找回密码功能未启用'}), 400
    
    data = request.json
    username = data.get('username')
    
    if not username:
        return jsonify({'error': '请输入用户名'}), 400
    
    user = User.query.filter_by(username=username).first()
    if not user:
        return jsonify({'error': '用户不存在'}), 404
    
    if not user.security_question:
        return jsonify({'error': '该用户未设置安全问题，请联系管理员重置密码'}), 400
    
    return jsonify({
        'success': True,
        'security_question': user.security_question
    })

@auth_bp.route('/api/auth/forgot-password/verify', methods=['POST'])
def api_forgot_password_verify():
    settings = get_settings()
    if not settings.get('allow_self_password_reset', False):
        return jsonify({'error': '自助找回密码功能未启用'}), 400
    
    data = request.json
    username = data.get('username')
    answer = data.get('answer')
    
    if not username or not answer:
        return jsonify({'error': '请填写完整信息'}), 400
    
    user = User.query.filter_by(username=username).first()
    if not user:
        return jsonify({'error': '用户不存在'}), 404
    
    if not user.security_question or not user.security_answer_hash:
        return jsonify({'error': '该用户未设置安全问题'}), 400
    
    if not user.check_security_answer(answer):
        return jsonify({'error': '安全问题答案错误'}), 400
    
    return jsonify({'success': True})

@auth_bp.route('/api/auth/forgot-password/reset', methods=['POST'])
def api_forgot_password_reset():
    settings = get_settings()
    if not settings.get('allow_self_password_reset', False):
        return jsonify({'error': '自助找回密码功能未启用'}), 400
    
    data = request.json
    username = data.get('username')
    answer = data.get('answer')
    new_password = data.get('new_password')
    
    if not username or not answer or not new_password:
        return jsonify({'error': '请填写完整信息'}), 400
    
    user = User.query.filter_by(username=username).first()
    if not user:
        return jsonify({'error': '用户不存在'}), 404
    
    if not user.security_question or not user.security_answer_hash:
        return jsonify({'error': '该用户未设置安全问题'}), 400
    
    if not user.check_security_answer(answer):
        return jsonify({'error': '安全问题答案错误'}), 400
    
    password_strength = settings.get('password_strength', 1)
    allow_weak_password = settings.get('allow_weak_password', False)
    
    is_valid_password, password_error = validate_password_strength(new_password, password_strength)
    if not is_valid_password:
        return jsonify({'error': password_error}), 400
    
    if not allow_weak_password and is_weak_password(new_password):
        return jsonify({'error': '密码过于简单，请使用更强的密码'}), 400
    
    user.set_password(new_password)
    db.session.commit()
    
    return jsonify({'success': True, 'message': '密码重置成功'})
