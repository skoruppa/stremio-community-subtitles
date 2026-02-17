import datetime
import uuid
import secrets
import json
from time import time

from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, BigInteger, SmallInteger, ForeignKey, Table, TypeDecorator, CHAR, select, UniqueConstraint
from sqlalchemy.orm import relationship, declarative_base
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.ext.mutable import MutableDict, MutableList
from werkzeug.security import generate_password_hash, check_password_hash
from quart import current_app
from .extensions import Base, async_session_maker

# Association table
roles_users = Table(
    'roles_users',
    Base.metadata,
    Column('user_id', Integer, ForeignKey('users.id')),
    Column('role_id', Integer, ForeignKey('roles.id'))
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


class Role(Base):
    __tablename__ = 'roles'
    id = Column(Integer, primary_key=True)
    name = Column(String(80), unique=True, nullable=False)
    description = Column(String(255))
    users = relationship('User', secondary=roles_users, back_populates='roles')

    def __repr__(self):
        return f'<Role {self.name}>'


class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    username = Column(String(80), unique=True, nullable=False, index=True)
    email = Column(String(120), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    preferred_languages = Column(MutableList.as_mutable(JSONType), default=list)
    active = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    manifest_token = Column(String(64), unique=True, nullable=True, index=True)
    email_confirmed = Column(Boolean, default=False)
    email_confirmed_at = Column(DateTime, nullable=True)
    show_no_subtitles = Column(Boolean, default=False)
    prioritize_ass_subtitles = Column(Boolean, default=False)
    prioritize_forced_subtitles = Column(Boolean, default=False)
    provider_credentials = Column(MutableDict.as_mutable(JSONType), nullable=True, default=dict)
    last_login_at = Column(DateTime)
    current_login_at = Column(DateTime)
    last_login_ip = Column(String(100))
    current_login_ip = Column(String(100))
    login_count = Column(Integer, default=0)

    roles = relationship('Role', secondary=roles_users, back_populates='users')
    uploaded_subtitles = relationship('Subtitle', back_populates='uploader')
    activity_log = relationship('UserActivity', back_populates='user')
    selections = relationship('UserSubtitleSelection', back_populates='user')
    votes = relationship('SubtitleVote', back_populates='user')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def generate_manifest_token(self):
        while True:
            token = secrets.token_urlsafe(32)
            # Note: In async context, this should be checked differently
            self.manifest_token = token
            break

    @staticmethod
    async def get_by_manifest_token(token):
        async with async_session_maker() as session:
            result = await session.execute(select(User).filter_by(manifest_token=token))
            return result.scalar_one_or_none()

    def has_role(self, role_name):
        return any(role.name == role_name for role in self.roles)

    @property
    def is_authenticated(self):
        return True

    @property
    def is_active(self):
        return self.active

    @property
    def is_anonymous(self):
        return False

    def get_id(self):
        return str(self.id)

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


class Subtitle(Base):
    __tablename__ = 'subtitles'
    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    content_id = Column(String(100), nullable=False, index=True)
    content_type = Column(String(20), nullable=False)
    video_hash = Column(String(50), nullable=True, index=True)
    language = Column(String(10), nullable=False, index=True)
    file_path = Column(String(255), nullable=True)
    hash = Column(String(64), nullable=True, index=True)
    uploader_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    upload_timestamp = Column(DateTime, default=datetime.datetime.utcnow, index=True)
    votes = Column(Integer, default=0, index=True)
    author = Column(String(100), nullable=True)
    version_info = Column(Text, nullable=True)
    source_type = Column(String(50), nullable=False, default='community', index=True)
    source_metadata = Column(MutableDict.as_mutable(JSONType), nullable=True)

    uploader = relationship('User', back_populates='uploaded_subtitles')
    user_votes = relationship('SubtitleVote', back_populates='subtitle')

    def __repr__(self):
        return f'<Subtitle id={self.id} lang={self.language} content={self.content_id} hash={self.video_hash} source={self.source_type}>'


class UserActivity(Base):
    __tablename__ = 'user_activity'
    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)
    content_id = Column(String(512), nullable=False, index=True)
    content_type = Column(String(20), nullable=False)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow, index=True)
    video_hash = Column(String(50), nullable=True)
    video_size = Column(BigInteger, nullable=True)
    video_filename = Column(Text, nullable=True)

    user = relationship('User', back_populates='activity_log')

    def __repr__(self):
        return f'<Activity user={self.user_id} content={self.content_id} time={self.timestamp}>'


class UserSubtitleSelection(Base):
    __tablename__ = 'user_subtitle_selections'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)
    content_id = Column(String(100), nullable=False, index=True)
    video_hash = Column(String(50), nullable=False, default='', index=True)  # Changed to NOT NULL with default ''
    language = Column(String(10), nullable=False, index=True)
    selected_subtitle_id = Column(GUID(), ForeignKey('subtitles.id'), nullable=True)
    selected_external_file_id = Column(Integer, nullable=True, index=True)
    external_details_json = Column(MutableDict.as_mutable(JSONType), nullable=True)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    user = relationship('User', back_populates='selections')
    selected_subtitle = relationship('Subtitle')

    __table_args__ = (
        UniqueConstraint('user_id', 'content_id', 'video_hash', 'language', name='uq_user_content_hash_language_selection'),
    )

    def __repr__(self):
        if self.selected_subtitle_id:
            return f'<UserSelection user={self.user_id} content={self.content_id} local_sub_id={self.selected_subtitle_id}>'
        elif self.selected_external_file_id:
            return f'<UserSelection user={self.user_id} content={self.content_id} opensub_file_id={self.selected_external_file_id}>'
        return f'<UserSelection user={self.user_id} content={self.content_id} (no selection)>'


class SubtitleVote(Base):
    __tablename__ = 'subtitle_votes'
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)
    subtitle_id = Column(GUID(), ForeignKey('subtitles.id'), nullable=False, index=True)
    vote_value = Column(SmallInteger, nullable=False)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    user = relationship('User', back_populates='votes')
    subtitle = relationship('Subtitle', back_populates='user_votes')

    __table_args__ = (UniqueConstraint('user_id', 'subtitle_id', name='uq_user_subtitle_vote'),)

    def __repr__(self):
        return f'<SubtitleVote user={self.user_id} sub={self.subtitle_id} value={self.vote_value}>'

