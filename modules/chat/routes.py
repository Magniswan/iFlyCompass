from flask import render_template, redirect, url_for
from flask_login import login_required, current_user
from models.chat import ChatRoom
from utils import get_settings
from . import chat_bp

@chat_bp.route('/board/chat')
@login_required
def chat():
    settings = get_settings()
    chat_rooms = ChatRoom.query.filter_by(is_active=True).all()
    return render_template('chat.html', 
                         username=current_user.display_name, 
                         passkey_used=current_user.passkey_used,
                         chat_rooms=chat_rooms, 
                         is_admin=current_user.is_admin, 
                         is_super_admin=current_user.is_super_admin,
                         sidebar_expanded=settings.get('sidebar_default_expanded', False))

@chat_bp.route('/board/chat-test/<room_name>')
@login_required
def chat_test(room_name):
    settings = get_settings()
    chat_room = ChatRoom.query.filter_by(name=room_name, is_active=True).first()
    if not chat_room:
        return redirect(url_for('chat.chat'))
    return render_template('chat-simple.html', 
                         username=current_user.display_name, 
                         passkey_used=current_user.passkey_used,
                         room=chat_room, 
                         is_admin=current_user.is_admin, 
                         is_super_admin=current_user.is_super_admin,
                         sidebar_expanded=settings.get('sidebar_default_expanded', False),
                         multi_user_mode=chat_room.multi_user_mode or False)
