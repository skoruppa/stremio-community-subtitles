"""Language switcher route"""
from quart import Blueprint, request, redirect, make_response
from datetime import datetime, timedelta

language_bp = Blueprint('language', __name__)


@language_bp.route('/set-language/<lang_code>')
async def set_language(lang_code):
    """Set user's preferred language via cookie"""
    from quart import current_app
    
    # Validate language code
    if lang_code not in current_app.config['LANGUAGES']:
        lang_code = 'en'
    
    # Get redirect URL from referrer or default to index
    redirect_url = request.referrer or '/'
    
    # Create response with language cookie
    response = await make_response(redirect(redirect_url))
    
    # Set cookie for 1 year
    expires = datetime.utcnow() + timedelta(days=365)
    response.set_cookie(
        'lang',
        lang_code,
        expires=expires,
        httponly=True,
        samesite='Lax'
    )
    
    return response
