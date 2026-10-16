"""Public share links."""
import secrets
from flask import request, url_for


def generate_share_token():
    return secrets.token_urlsafe(16)


def generate_share_url(token):
    """Generate share URL with proper scheme (HTTPS if available)"""
    # Determine the scheme from headers (in case behind reverse proxy)
    forwarded_proto = request.headers.get('X-Forwarded-Proto', request.scheme)
    scheme = forwarded_proto.split(',')[0].strip()  # Handle multi-value headers
    
    # Generate external URL with proper scheme
    return url_for("shared_list", token=token, _external=True, _scheme=scheme)
