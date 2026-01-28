from quart import Blueprint, current_app, request
from .utils import respond_with
from ..models import User
from ..version import VERSION

manifest_bp = Blueprint('manifest', __name__)

MANIFEST = {
    'id': 'com.community.stremio-subtitles',
    'version': VERSION,
    'name': 'Stremio Community Subtitles',
    'logo': 'https://host/static/logo.png',
    'description': 'Community-driven subtitle addon for Stremio with user accounts and uploading.',
    'types': ['movie', 'series'],
    'catalogs': [],
    'contactEmail': 'skoruppa@gmail.com',
    'behaviorHints': {'configurable': True, 'configurationRequired': True},
    'resources': ['subtitles'],
    "stremioAddonsConfig": {
        "issuer": "https://stremio-addons.net",
        "signature": "eyJhbGciOiJkaXIiLCJlbmMiOiJBMTI4Q0JDLUhTMjU2In0..E7iWDKmcd-Q7_crONeumAg.kVgF4xqlM92m-e9VtCSBSupdZr8s1R9KgamrC5UxNimSe8XpPtVxkwrUDxb9ACZe2o4hNkhPncsQuq-KyXHYMiRVAt_86UMEPit7ZGLMZAJCXac7k-vpkuqErzcIj93c.PN0ecXQ8X1mFF9g7VSv4DA"
    }
}


@manifest_bp.route('/<manifest_token>/manifest.json')
async def addon_manifest(manifest_token):
    user = await User.get_by_manifest_token(manifest_token)
    if not user:
        current_app.logger.warning(f"Manifest requested for invalid token: {manifest_token}")
    else:
        current_app.logger.info(f"Manifest for token: {manifest_token} (User: {user.username})")

    manifest_data = MANIFEST.copy()
    manifest_data['logo'] = f'https://{request.host}/static/logo.png'
    manifest_data['behaviorHints'] = manifest_data.get('behaviorHints', {}).copy()
    manifest_data['behaviorHints'].pop('configurationRequired', None)

    return respond_with(manifest_data)


@manifest_bp.route('/manifest.json')
async def generic_manifest():
    current_app.logger.info("Generic manifest requested.")
    manifest_data = MANIFEST.copy()
    manifest_data['logo'] = f'https://{request.host}/static/logo.png'
    manifest_data['behaviorHints'] = manifest_data.get('behaviorHints', {}).copy()
    manifest_data['behaviorHints']['configurationRequired'] = True
    manifest_data['behaviorHints']['configurable'] = True
    return respond_with(manifest_data)
