from flask_socketio import join_room, leave_room, emit
from utils import get_utc_plus_8_time
from config import Config

room_users = {}
message_history = {}

def register_socketio_events(socketio):
    
    @socketio.on('join_room')
    def handle_join_room(data):
        try:
            room = data.get('room')
            username = data.get('username')
            
            if not room or not username:
                return
            
            join_room(room)
            
            if room not in room_users:
                room_users[room] = []
            if username not in room_users[room]:
                room_users[room].append(username)
            
            current_time = get_utc_plus_8_time()
            emit('user_joined', {
                'username': username,
                'message': f'{username} 加入了聊天室',
                'timestamp': current_time.strftime('%H:%M:%S')
            }, room=room)
            
            emit('user_list', {
                'room': room,
                'users': room_users[room]
            }, room=room)
        except Exception as e:
            print(f"处理加入房间事件失败: {e}")
    
    @socketio.on('leave_room')
    def handle_leave_room(data):
        try:
            room = data.get('room')
            username = data.get('username')
            
            if not room or not username:
                return
            
            leave_room(room)
            
            if room in room_users and username in room_users[room]:
                room_users[room].remove(username)
            
            current_time = get_utc_plus_8_time()
            emit('user_left', {
                'username': username,
                'message': f'{username} 离开了聊天室',
                'timestamp': current_time.strftime('%H:%M:%S')
            }, room=room)
            
            emit('user_list', {
                'room': room,
                'users': room_users.get(room, [])
            }, room=room)
        except Exception as e:
            print(f"处理离开房间事件失败: {e}")
    
    @socketio.on('send_message')
    def handle_send_message(data):
        try:
            room = data.get('room')
            username = data.get('username')
            message = data.get('message')
            
            if not room or not username or not message:
                return
            
            if room not in message_history:
                message_history[room] = []
            
            current_time = get_utc_plus_8_time()
            message_data = {
                'username': username,
                'message': message,
                'timestamp': current_time.strftime('%H:%M:%S'),
                'is_self': False,
                'quoted_message': data.get('quoted_message'),
                'quoted_messages': data.get('quoted_messages')
            }
            
            message_history[room].append(message_data)
            
            if len(message_history[room]) > Config.MAX_MESSAGE_HISTORY:
                message_history[room] = message_history[room][-Config.MAX_MESSAGE_HISTORY:]
            
            emit('new_message', message_data, room=room)
        except Exception as e:
            print(f"处理发送消息事件失败: {e}")
    
    @socketio.on('get_message_history')
    def handle_get_message_history(data):
        try:
            room = data.get('room')
            username = data.get('username')
            
            if not room or not username:
                return
            
            history = message_history.get(room, [])
            
            for msg in history:
                msg['is_self'] = (msg['username'] == username)
            
            emit('message_history', {
                'room': room,
                'messages': history
            })
        except Exception as e:
            print(f"处理获取消息历史事件失败: {e}")
            emit('message_history', {
                'room': data.get('room', ''),
                'messages': []
            })
