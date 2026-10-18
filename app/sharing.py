"""Public share links."""
import secrets
from datetime import datetime
from flask import request, url_for
from config import read_env_variable


def generate_share_token():
    return secrets.token_urlsafe(16)


def generate_share_url(token):
    """Generate share URL with proper scheme (HTTPS if available)"""
    # Determine the scheme from headers (in case behind reverse proxy)
    forwarded_proto = request.headers.get('X-Forwarded-Proto', request.scheme)
    scheme = forwarded_proto.split(',')[0].strip()  # Handle multi-value headers
    
    # Generate external URL with proper scheme
    return url_for("shared_list", token=token, _external=True, _scheme=scheme)


def link_sharing_enabled():
    """Global switch for public share links (admin > advanced settings)."""
    return read_env_variable('ENABLE_LINK_SHARING', 'true').lower() == 'true'


def find_share_link(users, token):
    """Return (owner, link, usable) for a share token, or (None, None, False) if no link has it.
    usable is False when the link was deactivated or has expired (or its expiry date is unreadable)."""
    for user in users:
        for link in (user.get('sharing') or {}).get('public_links') or []:
            if link.get('token') == token:
                try:
                    expires_at = datetime.strptime(link['expires_at'], '%Y-%m-%d %H:%M:%S')
                except (KeyError, TypeError, ValueError):
                    return user, link, False
                usable = bool(link.get('is_active', True)) and datetime.now() <= expires_at
                return user, link, usable
    return None, None, False
