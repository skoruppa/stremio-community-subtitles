from flask import current_app, render_template
from flask_mail import Message
from threading import Thread
from .extensions import mail


def send_async_email(app, msg):
    """Send email asynchronously."""
    with app.app_context():
        mail.send(msg)


def send_email(subject, recipients, text_body, html_body, sender=None):
    """Send an email."""
    app = current_app._get_current_object()
    msg = Message(subject, recipients=recipients, sender=sender)
    msg.body = text_body
    msg.html = html_body

    # Send email asynchronously
    Thread(target=send_async_email, args=(app, msg)).start()


def send_confirmation_email(user):
    """Send an email confirmation to a user."""
    token = user.get_email_confirmation_token()
    send_email(
        subject='Stremio Community Subs - Confirm Your Email',
        recipients=[user.email],
        text_body=render_template('email/confirm_email.txt', user=user, token=token),
        html_body=render_template('email/confirm_email.html', user=user, token=token)
    )


def send_password_reset_email(user):
    """Send a password reset email to a user."""
    token = user.get_reset_password_token()
    send_email(
        subject='Stremio Community Subs - Reset Your Password',
        recipients=[user.email],
        text_body=render_template('email/reset_password.txt', user=user, token=token),
        html_body=render_template('email/reset_password.html', user=user, token=token)
    )
