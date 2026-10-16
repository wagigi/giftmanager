"""Avatar URLs and uploaded avatar files."""
import os
from pathlib import Path
from flask import current_app, url_for


UPLOADED_AVATAR_PREFIX = 'avatars/'
AVATAR_SIZE = 256  # Uploaded pictures are cropped to a square of this size

def avatar_url(avatar):
    """Return the URL of a user's avatar, whether built-in (static) or uploaded."""
    if avatar and avatar.startswith(UPLOADED_AVATAR_PREFIX):
        return url_for('uploaded_avatar', filename=avatar[len(UPLOADED_AVATAR_PREFIX):])
    return url_for('static', filename=avatar or 'icons/avatar1.png')

def delete_uploaded_avatar(avatar):
    """Remove an uploaded avatar file from disk (built-in avatars are left alone)."""
    if avatar and avatar.startswith(UPLOADED_AVATAR_PREFIX):
        filename = os.path.basename(avatar)
        try:
            Path(current_app.config['AVATARS_DIR'], filename).unlink(missing_ok=True)
        except OSError:
            pass
