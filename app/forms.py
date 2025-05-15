from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileAllowed, FileRequired
from wtforms import StringField, PasswordField, BooleanField, SubmitField, SelectField, TextAreaField
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
    submit = SubmitField('Upload Subtitle')


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
    submit = SubmitField('Update Preference')


class OpenSubtitlesLoginForm(FlaskForm):
    use_opensubtitles = BooleanField('Use OpenSubtitles Integration')
    opensubtitles_username = StringField(
        'OpenSubtitles Username', 
        validators=[Optional(), Length(max=255)], 
        render_kw={'placeholder': 'Your OpenSubtitles.com Username'}
    )
    opensubtitles_password = PasswordField(
        'OpenSubtitles Password', 
        validators=[Optional(), Length(min=0, max=255)], 
        render_kw={'placeholder': 'Your OpenSubtitles.com Password'}
    ) # min=0 to allow empty if not checked
    submit = SubmitField('Save OpenSubtitles Settings')
