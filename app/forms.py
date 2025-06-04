from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileAllowed, FileRequired
from wtforms import StringField, PasswordField, BooleanField, SubmitField, SelectField, TextAreaField
from wtforms.fields.numeric import IntegerField
from wtforms.validators import DataRequired, Email, EqualTo, Length, ValidationError, Optional
from .models import User


class LoginForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired()])
    remember_me = BooleanField('Remember Me')
    submit = SubmitField('Sign In')


class RegistrationForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired(), Length(min=3, max=80)])
    email = StringField('Email', validators=[DataRequired(), Email(), Length(max=120)])
    password = PasswordField('Password', validators=[DataRequired(), Length(min=8)])
    password2 = PasswordField('Confirm Password', validators=[DataRequired(), EqualTo('password')])
    preferred_language = SelectField('Preferred Subtitle Language', validators=[DataRequired()])
    submit = SubmitField('Register')

    def validate_username(self, username):
        user = User.query.filter_by(username=username.data).first()
        if user:
            raise ValidationError('Username already taken. Please choose a different one.')

    def validate_email(self, email):
        user = User.query.filter_by(email=email.data).first()
        if user:
            raise ValidationError('Email already registered. Please use a different email or sign in.')


class SubtitleUploadForm(FlaskForm):
    # Basic fields (always present)
    subtitle_file = FileField('Subtitle File (.srt, .sub, .txt, .ass, .ssa)', validators=[
        FileRequired(),
        FileAllowed(['srt', 'sub', 'txt', 'ass', 'ssa'], 'Only .srt, .sub, .txt, .ass, .ssa files allowed!')
    ])
    language = SelectField('Subtitle Language', validators=[DataRequired()])
    encoding = StringField('Encoding', default='utf8', validators=[Length(max=20)])
    fps = SelectField('FPS (Frames Per Second)',
                      choices=[('', 'Auto'), ('23.976', '23.976'), ('24', '24'), ('25', '25'), ('29.97', '29.97'),
                               ('30', '30')],
                      validators=[])
    author = StringField('Author (Optional)', validators=[Length(max=100)])
    version_info = TextAreaField('Version/Sync Info (Optional)', validators=[Length(max=500)])

    # Advanced upload fields (only shown for advanced upload)
    content_id = StringField('Content ID',
                             validators=[Optional()],
                             description='IMDB ID (e.g., tt1234567) or Kitsu ID (e.g., kitsu:12345)')
    content_type = SelectField('Content Type',
                               choices=[('movie', 'Movie'), ('series', 'TV Series')],
                               validators=[Optional()])
    season_number = IntegerField('Season Number',
                                 validators=[Optional()],
                                 description='Required for TV series (default: 1)')
    episode_number = IntegerField('Episode Number',
                                  validators=[Optional()],
                                  description='Required for TV series')

    submit = SubmitField('Upload Subtitle')

    def validate_content_id(self, field):
        """Custom validation for content_id field"""
        if field.data:
            content_id = field.data.strip()
            if not (content_id.startswith('tt') or content_id.startswith('kitsu:')):
                raise ValidationError(
                    'Content ID must be either IMDB ID (starting with "tt") or Kitsu ID (format "kitsu:12345")')

    def validate_episode_number(self, field):
        """Custom validation for episode_number - required when content_type is series"""
        if hasattr(self, 'content_type') and self.content_type.data == 'series':
            if not field.data:
                raise ValidationError('Episode number is required for TV series')


class ChangePasswordForm(FlaskForm):
    current_password = PasswordField('Current Password', validators=[DataRequired()])
    new_password = PasswordField('New Password', validators=[DataRequired(), Length(min=8)])
    confirm_password = PasswordField('Confirm New Password', validators=[DataRequired(), EqualTo('new_password')])
    submit = SubmitField('Change Password')


class ResetPasswordRequestForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email()])
    submit = SubmitField('Request Password Reset')


class ResetPasswordForm(FlaskForm):
    password = PasswordField('New Password', validators=[DataRequired(), Length(min=8)])
    password2 = PasswordField('Confirm Password', validators=[DataRequired(), EqualTo('password')])
    submit = SubmitField('Reset Password')


class LanguagePreferenceForm(FlaskForm):
    preferred_language = SelectField('Preferred Subtitle Language', validators=[DataRequired()])
    submit_language = SubmitField('Update Preference')


class OpenSubtitlesLoginForm(FlaskForm):
    use_opensubtitles = BooleanField('Use OpenSubtitles Integration')
    opensubtitles_username = StringField(
        'OpenSubtitles Username', 
        validators=[DataRequired(), Length(max=255)],
        render_kw={'placeholder': 'Your OpenSubtitles.com Username',
                   'autocomplete': 'off'}
    )
    opensubtitles_password = PasswordField(
        'OpenSubtitles Password', 
        validators=[DataRequired(), Length(max=255)],
        render_kw={'placeholder': 'Your OpenSubtitles.com Password',
                   'autocomplete': 'off'}
    )
    submit_opensubtitles = SubmitField('Save OpenSubtitles Settings')  