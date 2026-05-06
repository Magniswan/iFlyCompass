from datetime import datetime, timezone
from extensions import db

class NovelReadingProgress(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    novel_filename = db.Column(db.String(255), nullable=False)
    last_chapter_index = db.Column(db.Integer, default=0)
    last_read_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    
    __table_args__ = (db.UniqueConstraint('user_id', 'novel_filename', name='unique_user_novel_progress'),)
