"""Shared fixtures for the smoke tests.

app/app.py reads DATA_DIR, loads .env and creates its data files at import
time, so every test gets a fresh temporary DATA_DIR and a freshly (re)imported
`app` module. The tracked fixtures in app/ (users.json, ideas.json, .env) are
never read or written.
"""
import importlib
import json
import os
import sys
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from unittest import mock

import pytest

APP_DIR = Path(__file__).resolve().parent.parent / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

# Plain-text passwords of the users created below.
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

ENV_TEMPLATE = """SECRET_KEY='test-secret-key'
MAILJET_API_KEY=''
MAILJET_API_SECRET=''
SYSTEM_EMAIL=''
DELETE_DAYS='30'
OIDC_CLIENT_ID=''
OIDC_CLIENT_SECRET=''
OIDC_SERVER_METADATA_URL=''
OIDC_LOGOUT_URL=''
ENABLE_DEFAULT_LOGIN='true'
ENABLE_AUTO_REGISTRATION='false'
ENABLE_SELF_REGISTRATION='false'
ENABLE_LINK_SHARING='true'
REORDERING='true'
IMGENABLED='false'
"""

@lru_cache(maxsize=None)
def cached_password_hash(password):
    """argon2 hashing is slow; hash each test password once per session.
    Uses the app's own password_hash(), imported lazily so DATA_DIR is set first."""
    return sys.modules["app"].password_hash(password)


# Every setting app.py reads. They are removed from os.environ before import,
# because read_env_variable() and os.getenv() fall back to the process
# environment for keys missing from the test .env.
ENV_KEYS = [
    "SECRET_KEY", "MAILJET_API_KEY", "MAILJET_API_SECRET", "SYSTEM_EMAIL", "DELETE_DAYS",
    "OIDC_CLIENT_ID", "OIDC_CLIENT_SECRET", "OIDC_SERVER_METADATA_URL", "OIDC_LOGOUT_URL",
    "PRIMARY_OIDC_FIELD", "SECONDARY_OIDC_FIELD", "PRIMARY_DB_FIELD", "SECONDARY_DB_FIELD",
    "ENABLE_AUTO_REGISTRATION", "ENABLE_DEFAULT_LOGIN", "LOGIN_PAGE_MESSAGE", "REORDERING",
    "IMGENABLED", "ENABLE_LINK_SHARING", "ENABLE_SELF_REGISTRATION", "JOINING_CODE",
    "CURRENCY_SYMBOL", "CURRENCY_POSITION",
]


def _fmt(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def build_users(password_hash):
    """Users: an admin, alice and bob in family Smith, carol in family Jones,
    a family guest for Smith, and a shared list owned by alice and bob."""
    now = datetime.now()

    def user(username, full_name, **extra):
        data = {
            "username": username,
            "password": password_hash(PASSWORDS[username]) if username in PASSWORDS else "",
            "email": f"{username}@example.com",
            "full_name": full_name,
            "birthday": "2000-01-01",
            "avatar": "icons/avatar1.png",
            "admin": False,
        }
        data.update(extra)
        return data

    return [
        user("admin", "Admin User", admin=True),
        user(
            "alice",
            "Alice Smith",
            groups=["Smith"],
            sharing={
                "public_links": [
                    {
                        "token": SHARE_TOKEN,
                        "created_at": _fmt(now),
                        "expires_at": _fmt(now + timedelta(days=30)),
                        "is_active": True,
                        "name": "Alice list",
                        "created_by": "alice",
                        "allow_purchases": True,
                        "visitor_purchases": [],
                    },
                    {
                        "token": EXPIRED_TOKEN,
                        "created_at": _fmt(now - timedelta(days=60)),
                        "expires_at": _fmt(now - timedelta(days=1)),
                        "is_active": True,
                        "name": "Old list",
                        "created_by": "alice",
                        "allow_purchases": True,
                        "visitor_purchases": [],
                    },
                ]
            },
        ),
        user("bob", "Bob Smith", groups=["Smith"]),
        user("carol", "Carol Jones", groups=["Jones"]),
        user("guest_smith", "Smith Guest", guest=True, access_type="family", groups=["Smith"]),
        user("shared_smith", "Smith Shared List", shared_list=True, list_members=["alice", "bob"]),
    ]


def build_ideas():
    """Ideas. Id 2 (for alice, added and bought by bob) is the surprise case."""
    base = {"description": "", "link": "", "value": None, "image_path": "", "date_added": "2026-01-01 10:00:00"}
    return [
        dict(base, gift_idea_id=1, user_id="alice", gift_name="Alice own idea", added_by="alice", bought_by=None),
        dict(base, gift_idea_id=2, user_id="alice", gift_name="Secret telescope", added_by="bob", bought_by="bob",
             date_bought="2026-01-02 10:00:00"),
        dict(base, gift_idea_id=3, user_id="bob", gift_name="Bob own idea", added_by="bob", bought_by=None),
        dict(base, gift_idea_id=4, user_id="carol", gift_name="Carol own idea", added_by="carol", bought_by=None),
        dict(base, gift_idea_id=5, user_id="alice", gift_name="Alice second idea", added_by="alice", bought_by=None),
    ]


class Env:
    """Handle on the temporary data directory used by one test."""

    def __init__(self, module, data_dir):
        self.module = module
        self.data_dir = Path(data_dir)
        self.users_file = self.data_dir / "users.json"
        self.ideas_file = self.data_dir / "ideas.json"
        self.env_file = self.data_dir / ".env"

    def users(self):
        return json.loads(self.users_file.read_text())

    def ideas(self):
        return json.loads(self.ideas_file.read_text())

    def user(self, username):
        return next(u for u in self.users() if u["username"] == username)

    def idea(self, idea_id):
        return next(i for i in self.ideas() if i["gift_idea_id"] == idea_id)

    def write_users(self, users):
        self.users_file.write_text(json.dumps(users, indent=4))

    def write_ideas(self, ideas):
        self.ideas_file.write_text(json.dumps(ideas, indent=4))

    def set_env(self, key, value):
        """Rewrite one key of the test .env (read at call time by read_env_variable)."""
        lines = [l for l in self.env_file.read_text().splitlines() if not l.startswith(f"{key}=")]
        lines.append(f"{key}='{value}'")
        self.env_file.write_text("\n".join(lines) + "\n")


@pytest.fixture
def env(tmp_path):
    """Fresh DATA_DIR populated with test data, and `app` imported against it."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / ".env").write_text(ENV_TEMPLATE)

    # patch.dict restores os.environ on exit, including the keys that
    # load_dotenv() adds while app is imported.
    with mock.patch.dict(os.environ):
        for key in ENV_KEYS:
            os.environ.pop(key, None)
        os.environ["DATA_DIR"] = str(data_dir)

        if "app" in sys.modules:
            module = importlib.reload(sys.modules["app"])
        else:
            module = importlib.import_module("app")
        assert module.DATA_DIR == str(data_dir), "app was not imported against the temporary DATA_DIR"

        module.app.config["TESTING"] = True
        handle = Env(module, data_dir)
        handle.write_users(build_users(cached_password_hash))
        handle.write_ideas(build_ideas())

        yield handle


@pytest.fixture
def app_module(env):
    return env.module


@pytest.fixture
def client(env):
    return env.module.app.test_client()


@pytest.fixture
def make_client(env):
    """Factory for extra, independent test clients (separate sessions)."""
    return env.module.app.test_client


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
