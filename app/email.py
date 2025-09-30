from flask import current_app, render_template
from threading import Thread
import logging
import resend

logger = logging.getLogger(__name__)


def send_async_email_with_resend(app, sender, recipients, subject, html_body):
    with app.app_context():
        api_key = current_app.config.get('RESEND_API_KEY')
        if not api_key:
            logger.error("RESEND_API_KEY is not set. Cannot send email.")
            return

        resend.api_key = api_key

        params = {
            "from": sender,
            "to": recipients,
            "subject": subject,
            "html": html_body,
        }

        try:
            logger.info(f"Attempting to send email via Resend to: {recipients[0]}")
            email = resend.Emails.send(params)
            logger.info(f"Email sent successfully via Resend. Message ID: {email['id']}")
        except Exception as e:
            logger.error(f"Failed to send email via Resend API: {e}", exc_info=True)


def send_email(subject, recipients, text_body, html_body, sender=None):
    app = current_app._get_current_object()

    if sender is None:
        sender = app.config['MAIL_DEFAULT_SENDER']

    Thread(target=send_async_email_with_resend, args=(app, sender, recipients, subject, html_body)).start()


def send_confirmation_email(user):
    token = user.get_email_confirmation_token()
    send_email(
        subject='Stremio Community Subs - Confirm Your Email',
        recipients=[user.email],
        text_body=render_template('email/confirm_email.txt', user=user, token=token),
        html_body=render_template('email/confirm_email.html', user=user, token=token)
    )


def send_password_reset_email(user):
    token = user.get_reset_password_token()
    send_email(
        subject='Stremio Community Subs - Reset Your Password',
        recipients=[user.email],
        text_body=render_template('email/reset_password.txt', user=user, token=token),
        html_body=render_template('email/reset_password.html', user=user, token=token)
    )