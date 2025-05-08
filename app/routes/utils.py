from flask import jsonify, make_response, Response
from io import BytesIO

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
