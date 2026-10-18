"""Test data constants and helpers shared by the smoke tests (imported by conftest.py too)."""
from urllib.parse import urlparse

# Plain-text passwords of the users built in conftest.py.
PASSWORDS = {
    "admin": "adminpass",
    "alice": "alicepass",
    "bob": "bobpass",
    "carol": "carolpass",
    "guest_smith": "guestpass",
    "shared_smith": "sharedpass",  # shared lists have a hash too, login must still refuse them
}

SHARE_TOKEN = "valid-token"
EXPIRED_TOKEN = "expired-token"


def login(client, username, password=None):
    """Log in through the /login form. Returns the (non-followed) response."""
    if password is None:
        password = PASSWORDS[username]
    return client.post("/login", data={"username": username, "password": password})


def flashes(client):
    """Flash messages currently stored in the client's session, as (category, message)."""
    with client.session_transaction() as sess:
        return list(sess.get("_flashes", []))


def session_username(client):
    with client.session_transaction() as sess:
        return sess.get("username")


def is_redirect_to(response, path):
    """True if the response redirects to exactly this path (query string ignored)."""
    return (response.status_code in (301, 302, 303, 307, 308)
            and urlparse(response.headers["Location"]).path == path)
