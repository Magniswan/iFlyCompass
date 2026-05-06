from flask import jsonify, request
from flask_login import login_required, current_user
from utils import get_settings, update_settings, PASSWORD_STRENGTH_LEVELS
from . import settings_bp

@settings_bp.route('/api/settings', methods=['GET'])
@login_required
def get_all_settings():
    if not (current_user.is_admin or current_user.is_super_admin):
        return jsonify({'error': '权限不足'}), 403
    
    settings = get_settings()
    
    result = {
        'general': {
            'home_display': settings.get('home_display', 'nickname'),
            'allow_nickname': settings.get('allow_nickname', True),
            'nickname_min_length': settings.get('nickname_min_length', 2),
            'nickname_max_length': settings.get('nickname_max_length', 20),
            'sidebar_default_expanded': settings.get('sidebar_default_expanded', False),
            'card_layout': settings.get('card_layout', '1x4')
        },
        'security': {
            'username_manual_min': settings.get('username_manual_min', 3),
            'username_manual_max': settings.get('username_manual_max', 50),
            'username_register_min': settings.get('username_register_min', 3),
            'username_register_max': settings.get('username_register_max', 50),
            'password_strength': settings.get('password_strength', 1),
            'allow_weak_password': settings.get('allow_weak_password', False),
            'allow_self_password_reset': settings.get('allow_self_password_reset', False),
            'allow_change_password': settings.get('allow_change_password', True)
        },
        'password_strength_options': [
            {'value': 1, 'label': PASSWORD_STRENGTH_LEVELS[1]['name']},
            {'value': 2, 'label': PASSWORD_STRENGTH_LEVELS[2]['name']},
            {'value': 3, 'label': PASSWORD_STRENGTH_LEVELS[3]['name']},
            {'value': 4, 'label': PASSWORD_STRENGTH_LEVELS[4]['name']}
        ],
        'card_layout_options': [
            {'value': '1x3', 'label': '1×3'},
            {'value': '1x4', 'label': '1×4'},
            {'value': '2x3', 'label': '2×3'}
        ],
        'is_super_admin': current_user.is_super_admin
    }
    
    return jsonify(result)

@settings_bp.route('/api/settings/general', methods=['PUT'])
@login_required
def update_general_settings():
    if not (current_user.is_admin or current_user.is_super_admin):
        return jsonify({'error': '权限不足'}), 403
    
    data = request.json
    
    updates = {}
    
    if 'home_display' in data:
        if data['home_display'] in ['nickname', 'username']:
            updates['home_display'] = data['home_display']
    
    if 'allow_nickname' in data:
        updates['allow_nickname'] = bool(data['allow_nickname'])
    
    if 'nickname_min_length' in data:
        min_len = int(data['nickname_min_length'])
        if 1 <= min_len <= 50:
            updates['nickname_min_length'] = min_len
    
    if 'nickname_max_length' in data:
        max_len = int(data['nickname_max_length'])
        if 1 <= max_len <= 50:
            updates['nickname_max_length'] = max_len
    
    if 'sidebar_default_expanded' in data:
        updates['sidebar_default_expanded'] = bool(data['sidebar_default_expanded'])
    
    if 'card_layout' in data:
        if data['card_layout'] in ['1x3', '1x4', '2x3']:
            updates['card_layout'] = data['card_layout']
    
    if updates:
        update_settings(updates)
    
    return jsonify({'success': True, 'message': '通用设置已保存'})

@settings_bp.route('/api/settings/security', methods=['PUT'])
@login_required
def update_security_settings():
    if not (current_user.is_admin or current_user.is_super_admin):
        return jsonify({'error': '权限不足'}), 403
    
    data = request.json
    updates = {}
    
    if current_user.is_super_admin:
        if 'username_manual_min' in data:
            min_val = int(data['username_manual_min'])
            if min_val >= 1:
                updates['username_manual_min'] = min_val
        
        if 'username_manual_max' in data:
            max_val = int(data['username_manual_max'])
            if max_val >= 1:
                updates['username_manual_max'] = max_val
    
    if 'username_register_min' in data:
        min_val = int(data['username_register_min'])
        if min_val >= 1:
            updates['username_register_min'] = min_val
    
    if 'username_register_max' in data:
        max_val = int(data['username_register_max'])
        if max_val >= 1:
            updates['username_register_max'] = max_val
    
    if 'password_strength' in data:
        strength = int(data['password_strength'])
        if 1 <= strength <= 4:
            updates['password_strength'] = strength
    
    if 'allow_weak_password' in data:
        updates['allow_weak_password'] = bool(data['allow_weak_password'])
    
    if 'allow_self_password_reset' in data:
        updates['allow_self_password_reset'] = bool(data['allow_self_password_reset'])
    
    if 'allow_change_password' in data:
        updates['allow_change_password'] = bool(data['allow_change_password'])
    
    if updates:
        update_settings(updates)
    
    return jsonify({'success': True, 'message': '安全设置已保存'})

@settings_bp.route('/api/settings/reset', methods=['POST'])
@login_required
def reset_all_settings():
    if not current_user.is_super_admin:
        return jsonify({'error': '只有超级管理员可以重置设置'}), 403
    
    from utils import reset_settings
    reset_settings()
    
    return jsonify({'success': True, 'message': '设置已重置为默认值'})
