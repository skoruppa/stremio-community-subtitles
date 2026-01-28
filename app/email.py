"""Async email sending"""
from quart import current_app, render_template
import logging
import aiohttp
import asyncio

logger = logging.getLogger(__name__)


async def send_async_email_via_local_api(sender, recipients, subject, html_body):
    api_key = current_app.config.get('LOCAL_MAIL_API_KEY')
    api_url = current_app.config.get('LOCAL_MAIL_API_URL')

    if not api_key or not api_url:
        logger.error("Local mail API config missing")
        return

    payload = {
        "sender": sender,
        "recipients": recipients,
        "subject": subject,
        "html": html_body
    }

    headers = {
        "Content-Type": "application/json",
        "X-API-Key": api_key
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(api_url, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status == 200:
                    logger.info(f"Email sent via local API to: {recipients[0]}")
                else:
                    text = await response.text()
                    logger.error(f"Local API error: {response.status}, {text}")
    except Exception as e:
        logger.error(f"Failed to send via local API: {e}", exc_info=True)


async def send_async_email_with_resend(sender, recipients, subject, html_body):
    api_key = current_app.config.get('RESEND_API_KEY')
    if not api_key:
        logger.error("RESEND_API_KEY not set")
        return

    payload = {
        "from": sender,
        "to": recipients,
        "subject": subject,
        "html": html_body,
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post('https://api.resend.com/emails', json=payload, headers=headers) as response:
                if response.status == 200:
                    data = await response.json()
                    logger.info(f"Email sent via Resend. ID: {data.get('id')}")
                else:
                    text = await response.text()
                    logger.error(f"Resend API error: {response.status}, {text}")
    except Exception as e:
        logger.error(f"Failed to send via Resend: {e}", exc_info=True)


async def send_async_email_with_smtp(sender, recipients, subject, text_body, html_body):
    import aiosmtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart

    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From'] = sender
    msg['To'] = recipients[0]

    msg.attach(MIMEText(text_body, 'plain'))
    msg.attach(MIMEText(html_body, 'html'))

    try:
        await aiosmtplib.send(
            msg,
            hostname=current_app.config['MAIL_SERVER'],
            port=current_app.config['MAIL_PORT'],
            username=current_app.config.get('MAIL_USERNAME'),
            password=current_app.config.get('MAIL_PASSWORD'),
            use_tls=current_app.config.get('MAIL_USE_TLS', False),
            start_tls=current_app.config.get('MAIL_USE_STARTTLS', True),
        )
        logger.info(f"Email sent via SMTP to: {recipients[0]}")
    except Exception as e:
        logger.error(f"Failed to send via SMTP: {e}", exc_info=True)


async def send_email(subject, recipients, text_body, html_body, sender=None):
    if sender is None:
        sender = current_app.config['MAIL_DEFAULT_SENDER']

    email_method = current_app.config.get('EMAIL_METHOD')

    if email_method == 'resend':
        await send_async_email_with_resend(sender, recipients, subject, html_body)
    elif email_method == 'local_api':
        await send_async_email_via_local_api(sender, recipients, subject, html_body)
    else:
        await send_async_email_with_smtp(sender, recipients, subject, text_body, html_body)


async def send_confirmation_email(user):
    token = user.get_email_confirmation_token()
    await send_email(
        subject='Stremio Community Subs - Confirm Your Email',
        recipients=[user.email],
        text_body=await render_template('email/confirm_email.txt', user=user, token=token),
        html_body=await render_template('email/confirm_email.html', user=user, token=token)
    )


async def send_password_reset_email(user):
    token = user.get_reset_password_token()
    await send_email(
        subject='Stremio Community Subs - Reset Your Password',
        recipients=[user.email],
        text_body=await render_template('email/reset_password.txt', user=user, token=token),
        html_body=await render_template('email/reset_password.html', user=user, token=token)
    )