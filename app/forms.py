from quart_wtf import QuartForm
from quart_wtf.file import FileField, FileAllowed, FileRequired
from wtforms import StringField, PasswordField, BooleanField, SubmitField, SelectField, SelectMultipleField, TextAreaField
from wtforms.fields.numeric import IntegerField
from wtforms.validators import DataRequired, Email, EqualTo, Length, ValidationError, Optional
from .models import User
from .languages import LANGUAGES
from quart_babel import lazy_gettext as _l


class LoginForm(QuartForm):
    email = StringField(_l('Email'), validators=[DataRequired(), Email()])
    password = PasswordField(_l('Password'), validators=[DataRequired()])
    remember_me = BooleanField(_l('Remember Me'))
    submit = SubmitField(_l('Sign In'))


class RegistrationForm(QuartForm):
    username = StringField(_l('Username'), validators=[DataRequired(), Length(min=3, max=80)])
    email = StringField(_l('Email'), validators=[DataRequired(), Email(), Length(max=120)])
    password = PasswordField(_l('Password'), validators=[DataRequired(), Length(min=8)])
    password2 = PasswordField(_l('Confirm Password'), validators=[DataRequired(), EqualTo('password')])
    preferred_languages = SelectMultipleField(_l('Preferred Subtitle Languages'), choices=LANGUAGES, validators=[DataRequired()])
    submit = SubmitField(_l('Register'))

    async def async_validate(self):
        """Async validation for database checks"""
        from sqlalchemy import select
        from .extensions import async_session_maker
        
        async with async_session_maker() as session:
            # Check username
            result = await session.execute(select(User).filter_by(username=self.username.data))
            if result.scalar_one_or_none():
                self.username.errors.append('Username already taken. Please choose a different one.')
                return False
            
            # Check email
            result = await session.execute(select(User).filter_by(email=self.email.data))
            if result.scalar_one_or_none():
                self.email.errors.append('Email already registered. Please use a different email or sign in.')
                return False
        
        return True


class SubtitleUploadForm(QuartForm):
    # Basic fields (always present)
    subtitle_file = FileField(_l('Subtitle File (.srt, .sub, .txt, .ass, .ssa)'), validators=[
        FileRequired(),
        FileAllowed(['srt', 'sub', 'txt', 'ass', 'ssa'], _l('Only .srt, .sub, .txt, .ass, .ssa files allowed!'))
    ])
    language = SelectField(_l('Subtitle Language'), validators=[DataRequired()])
    encoding = StringField(_l('Encoding'), default='utf8', validators=[Length(max=20)])
    fps = SelectField(_l('FPS (Frames Per Second)'),
                      choices=[('', _l('Auto')), ('23.976', '23.976'), ('24', '24'), ('25', '25'), ('29.97', '29.97'),
                               ('30', '30')],
                      validators=[])
    author = StringField(_l('Author (Optional)'), validators=[Length(max=100)])
    version_info = TextAreaField(_l('Version/Sync Info (Optional)'), validators=[Length(max=500)])

    # Advanced upload fields (only shown for advanced upload)
    content_id = StringField(_l('Content ID'),
                             validators=[Optional()],
                             description=_l('IMDB ID (e.g., tt1234567) or Kitsu ID (e.g., kitsu:12345)'))
    content_type = SelectField(_l('Content Type'),
                               choices=[('movie', _l('Movie')), ('series', _l('TV Series'))],
                               validators=[Optional()])
    season_number = IntegerField(_l('Season Number'),
                                 validators=[Optional()],
                                 description=_l('Required for TV series (default: 1)'))
    episode_number = IntegerField(_l('Episode Number'),
                                  validators=[Optional()],
                                  description=_l('Required for TV series'))

    submit = SubmitField(_l('Upload Subtitle'))

    def validate_content_id(self, field):
        """Custom validation for content_id field"""
        if field.data:
            content_id = field.data.strip()
            
            # Parse Stremio format: tt1234567:1:3 or kitsu:12345:3
            if ':' in content_id:
                parts = content_id.split(':')
                
                # Handle IMDB format: tt1234567:season:episode
                if parts[0].startswith('tt') and len(parts) == 3:
                    try:
                        season = int(parts[1])
                        episode = int(parts[2])
                        # Auto-correct the form data
                        field.data = parts[0]  # Set to just tt1234567
                        self.content_type.data = 'series'
                        self.season_number.data = season
                        self.episode_number.data = episode
                        return
                    except (ValueError, IndexError):
                        pass
                
                # Handle Kitsu format: kitsu:12345:episode
                elif parts[0] == 'kitsu' and len(parts) == 3:
                    try:
                        episode = int(parts[2])
                        # Auto-correct the form data
                        field.data = f"{parts[0]}:{parts[1]}"  # Set to kitsu:12345
                        self.content_type.data = 'series'
                        self.episode_number.data = episode
                        return
                    except (ValueError, IndexError):
                        pass
            
            # Standard validation
            if not (content_id.startswith('tt') or content_id.startswith('kitsu:')):
                raise ValidationError(
                    _l('Content ID must be either IMDB ID (starting with "tt") or Kitsu ID (format "kitsu:12345")'))

    def validate_episode_number(self, field):
        """Custom validation for episode_number - required when content_type is series"""
        if hasattr(self, 'content_type') and self.content_type.data == 'series':
            if not field.data:
                raise ValidationError(_l('Episode number is required for TV series'))


class ChangePasswordForm(QuartForm):
    current_password = PasswordField(_l('Current Password'), validators=[DataRequired()])
    new_password = PasswordField(_l('New Password'), validators=[DataRequired(), Length(min=8)])
    confirm_password = PasswordField(_l('Confirm New Password'), validators=[DataRequired(), EqualTo('new_password')])
    submit = SubmitField(_l('Change Password'))


class ResetPasswordRequestForm(QuartForm):
    email = StringField(_l('Email'), validators=[DataRequired(), Email()])
    submit = SubmitField(_l('Request Password Reset'))


class ResetPasswordForm(QuartForm):
    password = PasswordField(_l('New Password'), validators=[DataRequired(), Length(min=8)])
    password2 = PasswordField(_l('Confirm Password'), validators=[DataRequired(), EqualTo('password')])
    submit = SubmitField(_l('Reset Password'))


class LanguagePreferenceForm(QuartForm):
    preferred_languages = SelectMultipleField(_l('Preferred Subtitle Languages'), choices=LANGUAGES, validators=[DataRequired()])
    submit_language = SubmitField(_l('Update Preference'))


class OpenSubtitlesLoginForm(QuartForm):
    use_opensubtitles = BooleanField(_l('Use OpenSubtitles Integration'))
    opensubtitles_username = StringField(
        _l('OpenSubtitles Username'), 
        validators=[DataRequired(), Length(max=255)],
        render_kw={'placeholder': _l('Your OpenSubtitles.com Username'),
                   'autocomplete': 'off'}
    )
    opensubtitles_password = PasswordField(
        _l('OpenSubtitles Password'), 
        validators=[DataRequired(), Length(max=255)],
        render_kw={'placeholder': _l('Your OpenSubtitles.com Password'),
                   'autocomplete': 'off'}
    )
    submit_opensubtitles = SubmitField(_l('Save OpenSubtitles Settings'))
