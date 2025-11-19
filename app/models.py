import datetime
import uuid
import secrets
import json
from time import time

from sqlalchemy import TypeDecorator, Text
from sqlalchemy.dialects.mysql import LONGTEXT
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.types import TypeDecorator, CHAR
from sqlalchemy.ext.mutable import MutableDict, MutableList
from .extensions import db, login_manager
from flask import current_app

# Association table for many-to-many relationship between users and roles
roles_users = db.Table(
    'roles_users',
    db.Column('user_id', db.Integer, db.ForeignKey('users.id')),
    db.Column('role_id', db.Integer, db.ForeignKey('roles.id'))
)


class GUID(TypeDecorator):
    """Platform-independent GUID type.

    Uses PostgreSQL's UUID type, otherwise uses CHAR(36), storing UUID as string.

    """

    impl = CHAR
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == 'postgresql':
            return dialect.type_descriptor(PG_UUID())
        else:
            return dialect.type_descriptor(CHAR(36))  # dla MySQL i innych

    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        if not isinstance(value, uuid.UUID):
            value = uuid.UUID(str(value))
        if dialect.name == 'postgresql':
            return value
        else:
            # dla MySQL konwertujemy do stringa 36 znaków
            return str(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return value
        return uuid.UUID(value)


class JSONType(TypeDecorator):
    """Platform-independent JSON type.
    
    Uses PostgreSQL's JSONB type for better performance and indexing,
    otherwise uses LONGTEXT and handles JSON serialization/deserialization manually.
    """
    
    impl = Text
    cache_ok = True
    
    def load_dialect_impl(self, dialect):
        if dialect.name == 'postgresql':
            return dialect.type_descriptor(JSONB())
        elif dialect.name in ('mysql', 'mariadb'):
            # Use LONGTEXT for MySQL/MariaDB to handle large JSON documents
            return dialect.type_descriptor(LONGTEXT())
        else:
            # Fallback to regular Text for other databases
            return dialect.type_descriptor(Text())
    
    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        if dialect.name == 'postgresql':
            # PostgreSQL handles JSON natively
            return value
        else:
            # For MySQL/MariaDB, serialize to JSON string
            return json.dumps(value)
    
    def process_result_value(self, value, dialect):
        if value is None:
            return value
        if dialect.name == 'postgresql':
            # PostgreSQL returns already parsed JSON
            return value
        else:
            # For MySQL/MariaDB, deserialize from JSON string
            try:
                return json.loads(value)
            except (ValueError, TypeError):
                # Handle case where value might not be valid JSON
                return value


class Role(db.Model):
    __tablename__ = 'roles'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), unique=True, nullable=False)
    description = db.Column(db.String(255))

    def __repr__(self):
        return f'<Role {self.name}>'


class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    preferred_languages = db.Column(MutableList.as_mutable(JSONType), default=list)
    active = db.Column(db.Boolean, default=False)  # Changed to False by default until email is confirmed
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    manifest_token = db.Column(db.String(64), unique=True, nullable=True, index=True)
    email_confirmed = db.Column(db.Boolean, default=False)
    email_confirmed_at = db.Column(db.DateTime, nullable=True)

    # Provider credentials - unified system for all subtitle providers
    # Format: {'provider_name': {'token': '...', 'active': True, 'base_url': '...', 'try_provide_ass': False, ...}, ...}
    provider_credentials = db.Column(MutableDict.as_mutable(JSONType), nullable=True, default=dict)

    last_login_at = db.Column(db.DateTime)
    current_login_at = db.Column(db.DateTime)
    last_login_ip = db.Column(db.String(100))
    current_login_ip = db.Column(db.String(100))
    login_count = db.Column(db.Integer, default=0)

    # Relationships
    roles = db.relationship('Role', secondary=roles_users,
                            backref=db.backref('users', lazy='dynamic'))

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def generate_manifest_token(self):
        """Generates a unique manifest token for the user."""
        while True:
            token = secrets.token_urlsafe(32)
            if not User.query.filter_by(manifest_token=token).first():
                self.manifest_token = token
                break

    @staticmethod
    def get_by_manifest_token(token):
        """Finds a user by their manifest token."""
        return User.query.filter_by(manifest_token=token).first()

    def has_role(self, role_name):
        """Check if user has a specific role."""
        return any(role.name == role_name for role in self.roles)

    def get_email_confirmation_token(self, expires_in=86400):
        """Generate a token for email confirmation that expires in 24 hours by default."""
        import json
        import base64
        import hmac
        import hashlib

        # Create payload
        payload = {'confirm_email': self.id, 'exp': time() + expires_in}

        # Convert payload to JSON and encode to base64
        json_payload = json.dumps(payload).encode('utf-8')
        b64_payload = base64.urlsafe_b64encode(json_payload).decode('utf-8').rstrip('=')

        # Create signature
        signature = hmac.new(
            current_app.config['SECRET_KEY'].encode('utf-8'),
            b64_payload.encode('utf-8'),
            hashlib.sha256
        ).digest()
        b64_signature = base64.urlsafe_b64encode(signature).decode('utf-8').rstrip('=')

        # Combine to create token
        return f"{b64_payload}.{b64_signature}"

    @staticmethod
    def verify_email_confirmation_token(token):
        """Verify the email confirmation token and return the user ID."""
        try:
            import json
            import base64
            import hmac
            import hashlib
            from time import time

            # Split token into payload and signature
            parts = token.split('.')
            if len(parts) != 2:
                return None

            b64_payload, b64_signature = parts

            # Verify signature
            expected_signature = hmac.new(
                current_app.config['SECRET_KEY'].encode('utf-8'),
                b64_payload.encode('utf-8'),
                hashlib.sha256
            ).digest()
            expected_b64_signature = base64.urlsafe_b64encode(expected_signature).decode('utf-8').rstrip('=')

            if not hmac.compare_digest(b64_signature, expected_b64_signature):
                return None

            # Decode payload
            # Add padding if needed
            padding_needed = len(b64_payload) % 4
            if padding_needed:
                b64_payload += '=' * (4 - padding_needed)

            json_payload = base64.urlsafe_b64decode(b64_payload.encode('utf-8')).decode('utf-8')
            payload = json.loads(json_payload)

            # Check expiration
            if payload.get('exp', 0) < time():
                return None

            return payload.get('confirm_email')
        except Exception as e:
            current_app.logger.error(f"Error verifying token: {e}")
            return None

    def get_reset_password_token(self, expires_in=3600):
        """Generate a token for password reset that expires in 1 hour by default."""
        import json
        import base64
        import hmac
        import hashlib

        # Create payload
        payload = {'reset_password': self.id, 'exp': time() + expires_in}

        # Convert payload to JSON and encode to base64
        json_payload = json.dumps(payload).encode('utf-8')
        b64_payload = base64.urlsafe_b64encode(json_payload).decode('utf-8').rstrip('=')

        # Create signature
        signature = hmac.new(
            current_app.config['SECRET_KEY'].encode('utf-8'),
            b64_payload.encode('utf-8'),
            hashlib.sha256
        ).digest()
        b64_signature = base64.urlsafe_b64encode(signature).decode('utf-8').rstrip('=')

        # Combine to create token
        return f"{b64_payload}.{b64_signature}"

    @staticmethod
    def verify_reset_password_token(token):
        """Verify the password reset token and return the user ID."""
        try:
            import json
            import base64
            import hmac
            import hashlib
            from time import time

            # Split token into payload and signature
            parts = token.split('.')
            if len(parts) != 2:
                return None

            b64_payload, b64_signature = parts

            # Verify signature
            expected_signature = hmac.new(
                current_app.config['SECRET_KEY'].encode('utf-8'),
                b64_payload.encode('utf-8'),
                hashlib.sha256
            ).digest()
            expected_b64_signature = base64.urlsafe_b64encode(expected_signature).decode('utf-8').rstrip('=')

            if not hmac.compare_digest(b64_signature, expected_b64_signature):
                return None

            # Decode payload
            # Add padding if needed
            padding_needed = len(b64_payload) % 4
            if padding_needed:
                b64_payload += '=' * (4 - padding_needed)

            json_payload = base64.urlsafe_b64decode(b64_payload.encode('utf-8')).decode('utf-8')
            payload = json.loads(json_payload)

            # Check expiration
            if payload.get('exp', 0) < time():
                return None

            return payload.get('reset_password')
        except Exception as e:
            current_app.logger.error(f"Error verifying token: {e}")
            return None

    def __repr__(self):
        return f'<User {self.username}>'


class Subtitle(db.Model):
    __tablename__ = 'subtitles'
    id = db.Column(GUID(), primary_key=True, default=uuid.uuid4)
    content_id = db.Column(db.String(100), nullable=False, index=True)
    content_type = db.Column(db.String(20), nullable=False)
    video_hash = db.Column(db.String(50), nullable=True, index=True)
    language = db.Column(db.String(10), nullable=False, index=True)
    file_path = db.Column(db.String(255), nullable=True) # Nullable now, for linked OpenSubtitles
    hash = db.Column(db.String(64), nullable=True, index=True) # SHA256 hash of the VTT content
    uploader_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    upload_timestamp = db.Column(db.DateTime, default=datetime.datetime.utcnow, index=True)
    votes = db.Column(db.Integer, default=0, index=True)
    author = db.Column(db.String(100), nullable=True)
    version_info = db.Column(db.Text, nullable=True)

    source_type = db.Column(db.String(50), nullable=False, default='community', index=True) # E.g., 'community', 'opensubtitles_link'
    source_metadata = db.Column(MutableDict.as_mutable(JSONType), nullable=True) 

    uploader = db.relationship('User', backref=db.backref('uploaded_subtitles', lazy=True))

    def __repr__(self):
        return f'<Subtitle id={self.id} lang={self.language} content={self.content_id} hash={self.video_hash} source={self.source_type}>'


class UserActivity(db.Model):
    __tablename__ = 'user_activity'
    id = db.Column(GUID(), primary_key=True, default=uuid.uuid4)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    content_id = db.Column(db.String(100), nullable=False, index=True)
    content_type = db.Column(db.String(20), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.datetime.utcnow, index=True)
    video_hash = db.Column(db.String(50), nullable=True)
    video_size = db.Column(db.BigInteger, nullable=True)
    video_filename = db.Column(db.Text, nullable=True)

    user = db.relationship('User', backref=db.backref('activity_log', lazy=True))

    def __repr__(self):
        return f'<Activity user={self.user_id} content={self.content_id} time={self.timestamp}>'


class UserSubtitleSelection(db.Model):
    __tablename__ = 'user_subtitle_selections'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    content_id = db.Column(db.String(100), nullable=False, index=True) # e.g. imdb_id:season:episode or imdb_id
    video_hash = db.Column(db.String(50), nullable=True, index=True) # OpenSubtitles hash or other video file hash
    language = db.Column(db.String(10), nullable=False, index=True) # Added language column

    # Fields for selecting a subtitle from our own database
    selected_subtitle_id = db.Column(GUID(), db.ForeignKey('subtitles.id'), nullable=True)
    
    # Fields for selecting a subtitle from OpenSubtitles
    # This is the 'file_id' from OpenSubtitles API (attributes.files[].file_id)
    selected_external_file_id = db.Column(db.Integer, nullable=True, index=True)
    
    # Store relevant details of the selected OpenSubtitle to avoid re-fetching constantly for display
    external_details_json = db.Column(MutableDict.as_mutable(JSONType), nullable=True)

    timestamp = db.Column(db.DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    user = db.relationship('User', backref=db.backref('selections', lazy='dynamic'))
    selected_subtitle = db.relationship('Subtitle') # For locally hosted subtitles

    # Ensure that for a given user, content_id, video_hash, and language, only one selection type is active.
    __table_args__ = (
        db.UniqueConstraint('user_id', 'content_id', 'video_hash', 'language', name='uq_user_content_hash_language_selection'),
    )

    def __repr__(self):
        if self.selected_subtitle_id:
            return f'<UserSelection user={self.user_id} content={self.content_id} local_sub_id={self.selected_subtitle_id}>'
        elif self.selected_external_file_id:
            return f'<UserSelection user={self.user_id} content={self.content_id} opensub_file_id={self.selected_external_file_id}>'
        return f'<UserSelection user={self.user_id} content={self.content_id} (no selection)>'


class SubtitleVote(db.Model):
    __tablename__ = 'subtitle_votes'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    subtitle_id = db.Column(GUID(), db.ForeignKey('subtitles.id'), nullable=False, index=True)
    vote_value = db.Column(db.SmallInteger, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    user = db.relationship('User', backref=db.backref('votes', lazy='dynamic'))
    subtitle = db.relationship('Subtitle', backref=db.backref('user_votes', lazy='dynamic'))

    __table_args__ = (db.UniqueConstraint('user_id', 'subtitle_id', name='uq_user_subtitle_vote'),)

    def __repr__(self):
        return f'<SubtitleVote user={self.user_id} sub={self.subtitle_id} value={self.vote_value}>'


# User loader for Flask-Login
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))
