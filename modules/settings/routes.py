from flask import render_template
from flask_login import login_required, current_user
from . import settings_bp

@settings_bp.route('/board/settings')
@login_required
def system_settings():
    if not (current_user.is_admin or current_user.is_super_admin):
        return render_template('error.html',
                             error_title='权限不足',
                             error_message='您没有权限访问此页面',
                             current_user=current_user), 403
    
    return render_template('system_settings.html',
                         current_user=current_user)
