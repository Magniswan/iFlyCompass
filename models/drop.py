from datetime import datetime, timezone
from extensions import db

class DropMessage(db.Model):
    __tablename__ = 'drop_message'
    
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    sender_name = db.Column(db.String(50), nullable=False)
    content = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    
    sender = db.relationship('User', backref=db.backref('drop_messages', lazy='dynamic'))

class DropSettings(db.Model):
    __tablename__ = 'drop_settings'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), unique=True, nullable=False)
    enabled = db.Column(db.Boolean, default=True)
    last_drop_at = db.Column(db.DateTime, nullable=True)
    
    user = db.relationship('User', backref=db.backref('drop_settings', uselist=False))

class DropBlacklist(db.Model):
    __tablename__ = 'drop_blacklist'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    blocked_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    
    __table_args__ = (
        db.UniqueConstraint('user_id', 'blocked_user_id', name='unique_blacklist'),
    )
    
    user = db.relationship('User', foreign_keys=[user_id], backref=db.backref('blocked_users', lazy='dynamic'))
    blocked_user = db.relationship('User', foreign_keys=[blocked_user_id])
