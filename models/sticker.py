from datetime import datetime, timezone
from extensions import db

class UserSticker(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    sticker_code = db.Column(db.String(20), nullable=False)
    sticker_type = db.Column(db.String(20), nullable=False)
    sticker_name = db.Column(db.String(100), nullable=True)
    description = db.Column(db.String(255), nullable=True)
    local_path = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    
    __table_args__ = (db.UniqueConstraint('user_id', 'sticker_code', name='unique_user_sticker'),)

class PackSticker(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    pack_code = db.Column(db.String(20), nullable=False)
    sticker_code = db.Column(db.String(50), nullable=False)
    sticker_name = db.Column(db.String(100), nullable=True)
    description = db.Column(db.String(255), nullable=True)
    local_path = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    
    __table_args__ = (db.UniqueConstraint('user_id', 'pack_code', 'sticker_code', name='unique_pack_sticker'),)
