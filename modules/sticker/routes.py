from flask import send_from_directory
from flask_login import login_required
from config import Config
from . import sticker_bp

@sticker_bp.route('/stickers/<path:filename>')
@login_required
def serve_sticker(filename):
    return send_from_directory(Config.STICKERS_DIR, filename)
