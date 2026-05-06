from datetime import datetime, timezone
from extensions import db

class VideoAccessControl(db.Model):
    __tablename__ = 'video_access_control'

    id = db.Column(db.Integer, primary_key=True)
    video_path = db.Column(db.String(500), unique=True, nullable=False)
    mode = db.Column(db.String(20), nullable=False, default='public')
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    creator = db.relationship('User', backref=db.backref('video_access_controls', lazy='dynamic'))

class VideoAccessUser(db.Model):
    __tablename__ = 'video_access_user'

    id = db.Column(db.Integer, primary_key=True)
    video_path = db.Column(db.String(500), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        db.UniqueConstraint('video_path', 'user_id', name='unique_video_access_user'),
    )

    user = db.relationship('User', foreign_keys=[user_id])
