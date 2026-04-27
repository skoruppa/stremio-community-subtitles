"""Internal endpoints for deployment automation.
Not exposed publicly — only accessible from localhost via deploy scripts."""
import os
from quart import Blueprint, request, jsonify

internal_bp = Blueprint('internal', __name__, url_prefix='/internal')

INTERNAL_TOKEN = os.environ.get('INTERNAL_API_TOKEN', '')


def _check_token():
    """Verify request comes with valid internal token."""
    if not INTERNAL_TOKEN:
        return False
    token = request.headers.get('X-Internal-Token', '')
    return token == INTERNAL_TOKEN


@internal_bp.route('/reload-anime', methods=['POST'])
async def reload_anime():
    if not _check_token():
        return jsonify({'error': 'unauthorized'}), 403

    from ..lib.anime_mapping import update_database
    try:
        updated = update_database()
        return jsonify({'updated': updated}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500
