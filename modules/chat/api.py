import re
from flask import jsonify, request
from flask_login import login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from extensions import db
from models.chat import ChatRoom
from models.user import User
from . import chat_bp

@chat_bp.route('/api/chatrooms', methods=['GET', 'POST', 'PUT', 'DELETE'])
@login_required
def manage_chatrooms():
    if request.method == 'GET':
        chat_rooms = ChatRoom.query.filter_by(is_active=True).all()
        return jsonify([{
            'id': room.id,
            'name': room.name,
            'has_password': bool(room.password),
            'created_by': room.created_by,
            'creator': User.query.get(room.created_by).username if room.created_by else '未知',
            'created_at': room.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            'is_owner': room.created_by == current_user.id,
            'multi_user_mode': room.multi_user_mode or False
        } for room in chat_rooms])
    
    elif request.method == 'POST':
        data = request.json
        name = data['name']
        password = data.get('password')
        
        if not re.match(r'^[\w\u4e00-\u9fa5]+$', name):
            return jsonify({'error': '聊天室名称只能包含中文、英文或数字'}), 400
        
        existing_room = ChatRoom.query.filter_by(name=name).first()
        if existing_room:
            return jsonify({'error': '聊天室名称已存在'}), 400
        
        chat_room = ChatRoom(
            name=name,
            created_by=current_user.id
        )
        
        if password:
            chat_room.password = generate_password_hash(password)
        
        db.session.add(chat_room)
        db.session.commit()
        
        return jsonify({
            'id': chat_room.id,
            'name': chat_room.name,
            'has_password': bool(chat_room.password),
            'created_by': chat_room.created_by,
            'creator': current_user.username,
            'created_at': chat_room.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            'is_owner': True,
            'multi_user_mode': False
        })
    
    elif request.method == 'PUT':
        data = request.json
        room_id = data['id']
        name = data['name']
        password = data.get('password')
        multi_user_mode = data.get('multi_user_mode')
        
        chat_room = ChatRoom.query.get(room_id)
        if not chat_room or not chat_room.is_active:
            return jsonify({'error': '聊天室不存在或已关闭'}), 404
        
        if chat_room.created_by != current_user.id and not current_user.is_admin:
            return jsonify({'error': '权限不足'}), 403
        
        if not re.match(r'^[\w\u4e00-\u9fa5]+$', name):
            return jsonify({'error': '聊天室名称只能包含中文、英文或数字'}), 400
        
        existing_room = ChatRoom.query.filter_by(name=name).filter(ChatRoom.id != room_id).first()
        if existing_room:
            return jsonify({'error': '聊天室名称已存在'}), 400
        
        chat_room.name = name
        if password:
            chat_room.password = generate_password_hash(password)
        elif password == '':
            chat_room.password = None
        
        if multi_user_mode is not None:
            chat_room.multi_user_mode = bool(multi_user_mode)
        
        db.session.commit()
        
        return jsonify({
            'id': chat_room.id,
            'name': chat_room.name,
            'has_password': bool(chat_room.password),
            'created_by': chat_room.created_by,
            'creator': User.query.get(chat_room.created_by).username if chat_room.created_by else '未知',
            'created_at': chat_room.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            'is_owner': chat_room.created_by == current_user.id,
            'multi_user_mode': chat_room.multi_user_mode or False
        })
    
    elif request.method == 'DELETE':
        data = request.json
        room_id = data['id']
        chat_room = ChatRoom.query.get(room_id)
        if not chat_room:
            return jsonify({'error': '聊天室不存在'}), 404
        
        if chat_room.created_by != current_user.id and not current_user.is_admin:
            return jsonify({'error': '权限不足'}), 403
        
        chat_room.is_active = False
        db.session.commit()
        return jsonify({'success': True})

@chat_bp.route('/api/chatrooms/<int:room_id>', methods=['DELETE'])
@login_required
def delete_chatroom(room_id):
    chat_room = ChatRoom.query.get(room_id)
    if not chat_room:
        return jsonify({'error': '聊天室不存在'}), 404
    
    if chat_room.created_by != current_user.id and not current_user.is_admin:
        return jsonify({'error': '权限不足'}), 403
    
    chat_room.is_active = False
    db.session.commit()
    return jsonify({'success': True})

@chat_bp.route('/api/chatroom/join', methods=['POST'])
@login_required
def join_chatroom():
    data = request.json
    room_id = data['room_id']
    password = data.get('password')
    
    chat_room = ChatRoom.query.get(room_id)
    if not chat_room or not chat_room.is_active:
        return jsonify({'error': '聊天室不存在或已关闭'}), 404
    
    if chat_room.password:
        if not current_user.is_super_admin and not current_user.is_admin:
            if not password or not check_password_hash(chat_room.password, password):
                return jsonify({'error': '密码错误'}), 401
    
    return jsonify({
        'success': True,
        'room_name': chat_room.name
    })
