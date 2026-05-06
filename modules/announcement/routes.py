from flask import render_template
from flask_login import login_required, current_user
from . import announcement_bp

@announcement_bp.route('/announcements')
@login_required
def announcement_center():
    return render_template('announcement_center.html', 
                          current_user=current_user)
