from quart_babel import gettext
from quart import Blueprint, render_template, redirect, url_for, flash, request, current_app, session
from quart_auth import login_user, logout_user, current_user, login_required, AuthUser
from urllib.parse import urlparse
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from ..models import User, Role
from ..forms import LoginForm, RegistrationForm, ChangePasswordForm, ResetPasswordRequestForm, ResetPasswordForm
from ..extensions import async_session_maker
from ..languages import LANGUAGES, LANGUAGE_DICT
from ..email import send_confirmation_email, send_password_reset_email
from iso639 import Lang

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/login', methods=['GET', 'POST'])
async def login():
    if await current_user.is_authenticated:
        return redirect(url_for('main.index'))

    if request.method == 'GET' and request.args.get('next'):
        session['next_url'] = request.args.get('next')
    
    form = await LoginForm.create_form()
    if await form.validate_on_submit():
        async with async_session_maker() as db_session:
            result = await db_session.execute(select(User).filter_by(email=form.email.data))
            user = result.scalar_one_or_none()
            
            if user is None or not user.check_password(form.password.data):
                await flash(gettext('Invalid email or password'), 'danger')
                return redirect(url_for('auth.login'))
            
            if not user.active:
                await flash(gettext('Please confirm your email address before logging in.'), 'warning')
                return redirect(url_for('auth.login'))
            
            # Update login tracking
            user.last_login_at = user.current_login_at
            user.current_login_at = datetime.utcnow()
            user.last_login_ip = user.current_login_ip
            ip = (
                request.headers.get('CF-Connecting-IP')
                or request.headers.get('X-Forwarded-For', '').split(',')[0]
                or request.headers.get('Client-IP')
                or request.remote_addr
            )
            user.current_login_ip = ip
            user.login_count = user.login_count + 1 if user.login_count else 1
            await db_session.commit()
            
            login_user(AuthUser(user.id), remember=form.remember_me.data)
            if form.remember_me.data:
                session.permanent = True
            current_app.logger.info(f"User {user.username} logged in")

            next_page = session.pop('next_url', None) or request.args.get('next')
            if not next_page and request.referrer:
                parsed_referrer = urlparse(request.referrer)
                if not parsed_referrer.netloc or parsed_referrer.netloc == request.host:
                    next_page = parsed_referrer.path
            
            if not next_page or (urlparse(next_page).netloc and urlparse(next_page).netloc != request.host):
                next_page = url_for('main.dashboard')
            return redirect(next_page)
    
    return await render_template('auth/login.html', title='Sign In', form=form)


@auth_bp.route('/logout')
async def logout():
    logout_user()
    session.clear()
    return redirect(url_for('main.index'))


@auth_bp.route('/register', methods=['GET', 'POST'])
async def register():
    if await current_user.is_authenticated:
        return redirect(url_for('main.index'))

    form = await RegistrationForm.create_form()
    form.preferred_languages.choices = LANGUAGES

    if not form.is_submitted:
        supported_iso_639_1_codes = []
        for code_639_2, _ in LANGUAGES:
            try:
                if code_639_2 == 'pob':
                    supported_iso_639_1_codes.append('por')
                else:
                    lang = Lang(code_639_2)
                    supported_iso_639_1_codes.append(lang.pt3)
            except KeyError:
                current_app.logger.warning(f"iso639-lang could not find ISO 639-3 for {code_639_2}")

        if supported_iso_639_1_codes:
            browser_prefs = request.accept_languages.values()
            best_match_3 = None
            for browser_pref in browser_prefs:
                try:
                    lang_code = browser_pref.split('-')[0].strip()
                    lang_obj = Lang(lang_code)
                    if lang_obj.pt3 in LANGUAGE_DICT:
                        best_match_3 = lang_obj.pt3
                        break
                except KeyError:
                    pass

            if best_match_3:
                form.preferred_languages.data = [best_match_3]

    if await form.validate_on_submit():
        # Additional async validation
        if not await form.async_validate():
            return await render_template('auth/register.html', title='Register', form=form)
        
        async with async_session_maker() as db_session:
            user = User(
                username=form.username.data,
                email=form.email.data,
                preferred_languages=form.preferred_languages.data,
                active=False
            )
            user.set_password(form.password.data)
            user.generate_manifest_token()
            
            if current_app.config.get('DISABLE_EMAIL_VERIFICATION', False):
                user.active = True
                user.email_confirmed = True
                user.email_confirmed_at = datetime.utcnow()

            # Add default role
            result = await db_session.execute(select(Role).filter_by(name='User'))
            user_role = result.scalar_one_or_none()
            if not user_role:
                user_role = Role(name='User', description='Standard user')
                db_session.add(user_role)

            user.roles.append(user_role)
            db_session.add(user)

            try:
                await db_session.commit()

                if not current_app.config.get('DISABLE_EMAIL_VERIFICATION', False):
                    try:
                        current_app.logger.info(f"Attempting to send confirmation email to {user.email}")
                        await send_confirmation_email(user)
                        await flash(gettext('A confirmation email has been sent.'), 'info')
                    except Exception as email_error:
                        current_app.logger.error(f"Failed to send confirmation email: {email_error}", exc_info=True)
                        await flash(gettext('Registration successful, but failed to send confirmation email. Please contact support.'), 'warning')
                else:
                    await flash(gettext('Registration successful! You can now log in.'), 'success')
                
                return redirect(url_for('auth.login'))

            except IntegrityError as e:
                await db_session.rollback()
                current_app.logger.warning(f"IntegrityError: {str(e)}")
                await flash(gettext('An error occurred during registration.'), 'danger')
                return await render_template('auth/register.html', title='Register', form=form)

            except Exception as e:
                await db_session.rollback()
                current_app.logger.error(f"Registration error: {str(e)}")
                await flash(gettext('An unexpected error occurred.'), 'danger')
                return await render_template('auth/register.html', title='Register', form=form)

    return await render_template('auth/register.html', title='Register', form=form)


@auth_bp.route('/change-password', methods=['GET', 'POST'])
@login_required
async def change_password():
    form = await ChangePasswordForm.create_form()
    if await form.validate_on_submit():
        user_id = current_user.auth_id
        async with async_session_maker() as db_session:
            user = await db_session.get(User, user_id)
            if not user.check_password(form.current_password.data):
                await flash(gettext('Current password is incorrect'), 'danger')
                return redirect(url_for('auth.change_password'))
            
            user.set_password(form.new_password.data)
            await db_session.commit()
            
        await flash(gettext('Your password has been updated'), 'success')
        return redirect(url_for('main.dashboard'))
    
    return await render_template('auth/change_password.html', title='Change Password', form=form)


@auth_bp.route('/reset-password-request', methods=['GET', 'POST'])
async def reset_password_request():
    if await current_user.is_authenticated:
        return redirect(url_for('main.index'))
    
    form = await ResetPasswordRequestForm.create_form()
    if await form.validate_on_submit():
        async with async_session_maker() as db_session:
            result = await db_session.execute(select(User).filter_by(email=form.email.data))
            user = result.scalar_one_or_none()
            if user:
                try:
                    current_app.logger.info(f"Attempting to send password reset email to {user.email}")
                    await send_password_reset_email(user)
                    await flash(gettext('Check your email for instructions'), 'info')
                except Exception as email_error:
                    current_app.logger.error(f"Failed to send password reset email: {email_error}", exc_info=True)
                    await flash(gettext('Failed to send reset email. Please try again later.'), 'danger')
            else:
                await flash(gettext('If that email is in our database, we sent a reset link'), 'info')
        return redirect(url_for('auth.login'))
    
    return await render_template('auth/reset_password_request.html', title='Reset Password', form=form)


@auth_bp.route('/resend-confirmation')
async def resend_confirmation():
    if await current_user.is_authenticated:
        return redirect(url_for('main.index'))
    return await render_template('auth/resend_confirmation.html', title='Resend Confirmation Email')


@auth_bp.route('/resend-confirmation', methods=['POST'])
async def resend_confirmation_post():
    if await current_user.is_authenticated:
        return redirect(url_for('main.index'))
    
    form = await request.form
    email = form.get('email')
    if not email:
        await flash(gettext('Email is required.'), 'danger')
        return redirect(url_for('auth.resend_confirmation'))
    
    async with async_session_maker() as db_session:
        result = await db_session.execute(select(User).filter_by(email=email))
        user = result.scalar_one_or_none()
        if user and not user.email_confirmed:
            try:
                current_app.logger.info(f"Resending confirmation email to {user.email}")
                await send_confirmation_email(user)
                await flash(gettext('A new confirmation email has been sent.'), 'info')
            except Exception as email_error:
                current_app.logger.error(f"Failed to resend confirmation email: {email_error}", exc_info=True)
                await flash(gettext('Failed to send confirmation email. Please try again later.'), 'danger')
        else:
            await flash(gettext('If that email is in our database and not confirmed, we sent a link.'), 'info')
    
    return redirect(url_for('auth.login'))


@auth_bp.route('/confirm-email/<token>')
async def confirm_email(token):
    if await current_user.is_authenticated:
        return redirect(url_for('main.index'))
    
    user_id = User.verify_email_confirmation_token(token)
    if not user_id:
        await flash(gettext('The confirmation link is invalid or has expired.'), 'danger')
        return redirect(url_for('auth.login'))
    
    async with async_session_maker() as db_session:
        user = await db_session.get(User, user_id)
        if not user:
            await flash(gettext('User not found.'), 'danger')
            return redirect(url_for('auth.login'))
        
        if user.email_confirmed:
            await flash(gettext('Your email has already been confirmed.'), 'info')
            return redirect(url_for('auth.login'))
        
        user.email_confirmed = True
        user.email_confirmed_at = datetime.utcnow()
        user.active = True
        await db_session.commit()
    
    await flash(gettext('Your email has been confirmed. You can now log in.'), 'success')
    return redirect(url_for('auth.login'))


@auth_bp.route('/reset-password/<token>', methods=['GET', 'POST'])
async def reset_password(token):
    if await current_user.is_authenticated:
        return redirect(url_for('main.index'))
    
    user_id = User.verify_reset_password_token(token)
    if not user_id:
        await flash(gettext('The reset link is invalid or has expired.'), 'danger')
        return redirect(url_for('auth.reset_password_request'))
    
    async with async_session_maker() as db_session:
        user = await db_session.get(User, user_id)
        if not user:
            await flash(gettext('User not found.'), 'danger')
            return redirect(url_for('auth.reset_password_request'))
        
        form = await ResetPasswordForm.create_form()
        if await form.validate_on_submit():
            user.set_password(form.password.data)
            await db_session.commit()
            await flash(gettext('Your password has been reset.'), 'success')
            return redirect(url_for('auth.login'))
    
    return await render_template('auth/reset_password.html', title='Reset Password', form=form, token=token)
