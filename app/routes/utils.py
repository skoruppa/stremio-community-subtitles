from flask import jsonify, make_response, Response, current_app
from io import BytesIO
from sqlalchemy.orm import joinedload
from ..models import UserSubtitleSelection, Subtitle, SubtitleVote
from ..extensions import db


def respond_with(data) -> Response:
    """Create a JSON response with CORS headers."""
    resp = jsonify(data)
    resp.headers['Access-Control-Allow-Origin'] = "*"
    resp.headers['Access-Control-Allow-Headers'] = '*'
    return resp


def return_srt_file(data, filename) -> Response:
    """Return subtitle file as a downloadable attachment."""
    if not data:
        return make_response("No data to return", 400)

    buffer = BytesIO(data.encode("utf-8"))
    resp = make_response(buffer.getvalue())
    resp.headers.update({
        "Content-Disposition": f"attachment; filename={filename}.srt",
        "Content-Type": "application/x-subrip",
        "Content-Length": str(len(data.encode("utf-8")))
    })
    return resp


def get_active_subtitle_details(user, content_id, video_hash=None):
    """
    Determines the active subtitle for a user, content, and video hash.
    This includes checking user's explicit selection (local or OpenSubtitles)
    or falling back to a default local subtitle.

    Args:
        user (User): The current user object.
        content_id (str): The content ID (e.g., IMDB ID, or IMDB_ID:S:E).
        video_hash (str, optional): The hash of the video file.

    Returns:
        dict: A dictionary containing:
            'type' (str): 'local', 'opensubtitles_selection', or 'none'.
            'subtitle' (Subtitle, optional): The Subtitle object if type is 'local'.
            'details' (dict, optional): JSON details if type is 'opensubtitles_selection'.
            'user_vote_value' (int, optional): User's vote on the local subtitle, if applicable.
            'user_selection_record' (UserSubtitleSelection, optional): The raw selection record.
    """
    active_details = {'type': 'none', 'subtitle': None, 'details': None, 'user_vote_value': None,
                      'user_selection_record': None, 'auto': False}

    # 1. Check for an explicit user selection
    user_selection_query = UserSubtitleSelection.query.filter_by(
        user_id=user.id,
        content_id=content_id
    )
    if video_hash:  # Match hash if available
        user_selection_query = user_selection_query.filter_by(video_hash=video_hash)
    else:  # If no video_hash for context, look for selections made without a hash
        user_selection_query = user_selection_query.filter(UserSubtitleSelection.video_hash.is_(None))

    user_selection = user_selection_query.options(
        joinedload(UserSubtitleSelection.selected_subtitle).joinedload(Subtitle.uploader)
    ).first()

    active_details['user_selection_record'] = user_selection

    if user_selection:
        if user_selection.selected_subtitle_id:
            active_details['type'] = 'local'
            active_details['subtitle'] = user_selection.selected_subtitle
            if active_details['subtitle']:
                user_vote = SubtitleVote.query.filter_by(
                    user_id=user.id,
                    subtitle_id=active_details['subtitle'].id
                ).first()
                if user_vote:
                    active_details['user_vote_value'] = user_vote.vote_value
            return active_details

        if user.opensubtitles_active and user_selection.selected_external_file_id and user_selection.external_details_json:
            # Only consider OpenSubtitles selection if integration is active for the user
            active_details['type'] = 'opensubtitles_selection'
            active_details['details'] = user_selection.external_details_json
            return active_details

    # 2. If no explicit user selection, or if OS selection is ignored due to inactive integration,
    # try to find a default local subtitle.
    # This fallback only applies if no valid explicit selection was found and returned above.
    default_local_subtitle_query = Subtitle.query.filter_by(
        content_id=content_id,
        language=user.preferred_language
    )
    if video_hash:
        default_local_subtitle_query = default_local_subtitle_query.filter_by(video_hash=video_hash)
    else:  # If no video_hash for context, prefer subs without a hash
        default_local_subtitle_query = default_local_subtitle_query.filter(Subtitle.video_hash.is_(None))

    default_local_subtitle = default_local_subtitle_query.order_by(Subtitle.votes.desc()) \
        .options(joinedload(Subtitle.uploader)).first()

    if default_local_subtitle:
        active_details['type'] = 'local'
        active_details['auto'] = True
        active_details['subtitle'] = default_local_subtitle
        user_vote = SubtitleVote.query.filter_by(
            user_id=user.id,
            subtitle_id=default_local_subtitle.id
        ).first()
        if user_vote:
            active_details['user_vote_value'] = user_vote.vote_value

    # If still no subtitle found, type remains 'none'
    return active_details
