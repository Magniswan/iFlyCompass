from flask import jsonify, request
from flask_login import login_required, current_user
from datetime import datetime, timezone
from extensions import db
from models import Announcement, UserAnnouncementStatus
from . import announcement_bp

@announcement_bp.route('/api/announcements', methods=['GET'])
@login_required
def get_announcements():
    announcement_type = request.args.get('type', 'all')
    query = Announcement.query.filter_by(is_active=True)
    
    if announcement_type != 'all':
        query = query.filter_by(announcement_type=announcement_type)
    
    announcements = query.order_by(Announcement.created_at.desc()).all()
    
    user_statuses = {}
    statuses = UserAnnouncementStatus.query.filter_by(user_id=current_user.id).all()
    for status in statuses:
        user_statuses[status.announcement_id] = status
    
    result = []
    for ann in announcements:
        ann_dict = ann.to_dict()
        status = user_statuses.get(ann.id)
        ann_dict['is_dismissed'] = status.is_dismissed if status else False
        ann_dict['session_dismissed'] = status.session_dismissed if status else False
        result.append(ann_dict)
    
    return jsonify(result)

@announcement_bp.route('/api/announcements/banner', methods=['GET'])
@login_required
def get_banner_announcement():
    banner = Announcement.query.filter_by(
        announcement_type='banner',
        is_active=True
    ).order_by(Announcement.priority.desc(), Announcement.created_at.desc()).first()
    
    if banner:
        return jsonify(banner.to_dict())
    return jsonify(None)

@announcement_bp.route('/api/announcements/notifications/popup', methods=['GET'])
@login_required
def get_popup_notifications():
    announcements = Announcement.query.filter_by(
        announcement_type='notification',
        is_active=True
    ).filter(Announcement.priority.in_(['important', 'normal'])).order_by(Announcement.priority.desc(), Announcement.created_at.desc()).all()
    
    user_statuses = {}
    statuses = UserAnnouncementStatus.query.filter_by(user_id=current_user.id).all()
    for status in statuses:
        user_statuses[status.announcement_id] = status
    
    result = []
    for ann in announcements:
        status = user_statuses.get(ann.id)
        
        if ann.priority == 'important':
            result.append(ann.to_dict())
        elif ann.priority == 'normal':
            if status and (status.is_dismissed or status.session_dismissed):
                continue
            result.append(ann.to_dict())
    
    return jsonify(result)

@announcement_bp.route('/api/announcements/badge', methods=['GET'])
@login_required
def get_announcement_badge():
    announcements = Announcement.query.filter_by(
        announcement_type='notification',
        is_active=True
    ).all()
    
    user_statuses = {}
    statuses = UserAnnouncementStatus.query.filter_by(user_id=current_user.id).all()
    for status in statuses:
        user_statuses[status.announcement_id] = status
    
    has_important = False
    normal_unread_count = 0
    has_minor_unread = False
    
    for ann in announcements:
        status = user_statuses.get(ann.id)
        
        if ann.priority == 'important':
            has_important = True
        elif ann.priority == 'normal':
            if not status or (not status.is_dismissed and not status.session_dismissed):
                normal_unread_count += 1
        elif ann.priority == 'minor':
            if not status or not status.is_dismissed:
                has_minor_unread = True
    
    if has_important:
        return jsonify({'type': 'exclamation'})
    elif normal_unread_count > 0:
        return jsonify({'type': 'number', 'count': normal_unread_count})
    elif has_minor_unread:
        return jsonify({'type': 'dot'})
    else:
        return jsonify({'type': 'none'})

@announcement_bp.route('/api/announcements/<int:announcement_id>/dismiss', methods=['POST'])
@login_required
def dismiss_announcement(announcement_id):
    announcement = Announcement.query.get(announcement_id)
    if not announcement:
        return jsonify({'error': '公告不存在'}), 404
    
    if announcement.announcement_type == 'banner' and announcement.priority == 'important':
        return jsonify({'error': '重要横幅公告无法关闭'}), 400
    
    status = UserAnnouncementStatus.query.filter_by(
        user_id=current_user.id,
        announcement_id=announcement_id
    ).first()
    
    if not status:
        status = UserAnnouncementStatus(
            user_id=current_user.id,
            announcement_id=announcement_id
        )
        db.session.add(status)
    
    status.session_dismissed = True
    db.session.commit()
    
    return jsonify({'success': True})

@announcement_bp.route('/api/announcements/<int:announcement_id>/confirm', methods=['POST'])
@login_required
def confirm_announcement(announcement_id):
    announcement = Announcement.query.get(announcement_id)
    if not announcement:
        return jsonify({'error': '公告不存在'}), 404
    
    status = UserAnnouncementStatus.query.filter_by(
        user_id=current_user.id,
        announcement_id=announcement_id
    ).first()
    
    if not status:
        status = UserAnnouncementStatus(
            user_id=current_user.id,
            announcement_id=announcement_id
        )
        db.session.add(status)
    
    status.session_dismissed = True
    db.session.commit()
    
    return jsonify({'success': True})

@announcement_bp.route('/api/announcements/<int:announcement_id>/never-show', methods=['POST'])
@login_required
def never_show_announcement(announcement_id):
    announcement = Announcement.query.get(announcement_id)
    if not announcement:
        return jsonify({'error': '公告不存在'}), 404
    
    if announcement.priority == 'important':
        return jsonify({'error': '重要公告无法设置不再提示'}), 400
    
    status = UserAnnouncementStatus.query.filter_by(
        user_id=current_user.id,
        announcement_id=announcement_id
    ).first()
    
    if not status:
        status = UserAnnouncementStatus(
            user_id=current_user.id,
            announcement_id=announcement_id
        )
        db.session.add(status)
    
    status.is_dismissed = True
    status.dismissed_at = datetime.now(timezone.utc)
    db.session.commit()
    
    return jsonify({'success': True})

@announcement_bp.route('/api/announcements/manage', methods=['GET'])
@login_required
def get_all_announcements_for_manage():
    if not (current_user.is_admin or current_user.is_super_admin):
        return jsonify({'error': '权限不足'}), 403
    
    announcements = Announcement.query.order_by(Announcement.created_at.desc()).all()
    return jsonify([ann.to_dict() for ann in announcements])

@announcement_bp.route('/api/announcements/manage', methods=['POST'])
@login_required
def create_announcement():
    if not (current_user.is_admin or current_user.is_super_admin):
        return jsonify({'error': '权限不足'}), 403
    
    data = request.json
    
    announcement_type = data.get('announcement_type', 'notification')
    priority = data.get('priority', 'normal')
    
    if announcement_type == 'banner':
        if priority == 'important' and not current_user.is_super_admin:
            return jsonify({'error': '只有超级管理员可以创建重要横幅公告'}), 403
        
        if priority == 'normal' and not current_user.is_super_admin and not current_user.is_admin:
            return jsonify({'error': '只有管理员可以创建一般横幅公告'}), 403
        
        existing_banner = Announcement.query.filter_by(
            announcement_type='banner',
            is_active=True
        ).first()
        
        if existing_banner:
            existing_banner.is_active = False
    
    if announcement_type == 'notification':
        if priority == 'important' and not current_user.is_super_admin:
            return jsonify({'error': '只有超级管理员可以创建重要通知公告'}), 403
    
    announcement = Announcement(
        title=data.get('title'),
        content=data.get('content'),
        announcement_type=announcement_type,
        priority=priority,
        created_by=current_user.id
    )
    
    db.session.add(announcement)
    db.session.commit()
    
    return jsonify(announcement.to_dict())

@announcement_bp.route('/api/announcements/manage/<int:announcement_id>', methods=['PUT'])
@login_required
def update_announcement(announcement_id):
    if not (current_user.is_admin or current_user.is_super_admin):
        return jsonify({'error': '权限不足'}), 403
    
    announcement = Announcement.query.get(announcement_id)
    if not announcement:
        return jsonify({'error': '公告不存在'}), 404
    
    data = request.json
    
    if announcement.priority == 'important' and not current_user.is_super_admin:
        return jsonify({'error': '只有超级管理员可以编辑重要公告'}), 403
    
    if announcement.announcement_type == 'banner' and announcement.priority == 'important' and not current_user.is_super_admin:
        return jsonify({'error': '只有超级管理员可以编辑重要横幅公告'}), 403
    
    if 'title' in data:
        announcement.title = data['title']
    if 'content' in data:
        announcement.content = data['content']
    if 'priority' in data:
        new_priority = data['priority']
        if new_priority == 'important' and not current_user.is_super_admin:
            return jsonify({'error': '只有超级管理员可以将公告设为重要'}), 403
        announcement.priority = new_priority
    
    db.session.commit()
    
    return jsonify(announcement.to_dict())

@announcement_bp.route('/api/announcements/manage/<int:announcement_id>', methods=['DELETE'])
@login_required
def delete_announcement(announcement_id):
    if not (current_user.is_admin or current_user.is_super_admin):
        return jsonify({'error': '权限不足'}), 403
    
    announcement = Announcement.query.get(announcement_id)
    if not announcement:
        return jsonify({'error': '公告不存在'}), 404
    
    if announcement.priority == 'important' and not current_user.is_super_admin:
        return jsonify({'error': '只有超级管理员可以删除重要公告'}), 403
    
    UserAnnouncementStatus.query.filter_by(announcement_id=announcement_id).delete()
    
    db.session.delete(announcement)
    db.session.commit()
    
    return jsonify({'success': True})
