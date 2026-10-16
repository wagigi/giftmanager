"""Runtime-editable settings are read from DATA_DIR/.env at call time.

Each test edits the test .env (with the same writer as the admin pages) after
`app` was imported, and checks that the new value applies without re-importing
anything. os.environ is never touched here: the conftest removed these keys
from it before import, so only the .env file can supply them.
"""
from unittest import mock

import pytest

from smoke_helpers import is_redirect_to, login, session_username


# Mailjet -----------------------------------------------------------------------

def test_mailjet_api_key_is_read_at_call_time(env, mailer_module):
    env.set_env("MAILJET_API_SECRET", "new-secret")
    with mock.patch.object(mailer_module, "Client") as mailjet_client:
        assert mailer_module.get_mailjet_client() is None  # key still empty
        env.set_env("MAILJET_API_KEY", "new-key")
        assert mailer_module.get_mailjet_client() is mailjet_client.return_value
    mailjet_client.assert_called_once_with(auth=("new-key", "new-secret"), version="v3.1")


def test_mailjet_api_secret_is_read_at_call_time(env, mailer_module):
    env.set_env("MAILJET_API_KEY", "new-key")
    with mock.patch.object(mailer_module, "Client") as mailjet_client:
        assert mailer_module.get_mailjet_client() is None  # secret still empty
        env.set_env("MAILJET_API_SECRET", "new-secret")
        assert mailer_module.get_mailjet_client() is mailjet_client.return_value
    mailjet_client.assert_called_once_with(auth=("new-key", "new-secret"), version="v3.1")


def test_system_email_is_read_at_call_time(client, env, mailer_module):
    """Deleting a bought idea emails the buyer from SYSTEM_EMAIL (Client is mocked)."""
    env.set_env("MAILJET_API_KEY", "new-key")
    env.set_env("MAILJET_API_SECRET", "new-secret")
    env.set_env("SYSTEM_EMAIL", "noreply@new.example.com")
    login(client, "alice")
    with mock.patch.object(mailer_module, "Client") as mailjet_client:
        assert client.delete("/delete_idea/2").status_code == 204
    send = mailjet_client.return_value.send.create
    send.assert_called_once()
    message = send.call_args.kwargs["data"]["Messages"][0]
    assert message["From"]["Email"] == "noreply@new.example.com"
    assert message["To"][0]["Email"] == "bob@example.com"


def test_edit_email_settings_shows_current_system_email(client, env):
    login(client, "admin")
    env.set_env("SYSTEM_EMAIL", "first@example.com")
    assert 'value="first@example.com"' in client.get("/edit_email_settings").get_data(as_text=True)
    env.set_env("SYSTEM_EMAIL", "second@example.com")
    assert 'value="second@example.com"' in client.get("/edit_email_settings").get_data(as_text=True)


# OIDC matching fields (/auth with the OIDC provider mocked, no network) ---------

OIDC_USER_INFO = {
    "email": "bob@example.com",
    "alt_email": "carol@example.com",
    "preferred_username": "alice",
    "nickname": "carol",
}


def oidc_login(make_client, app_module, user_info=OIDC_USER_INFO):
    """Run /auth in a fresh client with the provider calls mocked.
    Returns (response, username logged in or None)."""
    client = make_client()
    with client.session_transaction() as sess:
        sess["state"] = "test-state"
        sess["nonce"] = "test-nonce"
    keycloak = app_module.oauth.keycloak
    with mock.patch.object(keycloak, "authorize_access_token", return_value={"id_token": "x"}), \
            mock.patch.object(keycloak, "parse_id_token", return_value=dict(user_info)):
        response = client.get("/auth?state=test-state")
    return response, session_username(client)


def test_primary_oidc_field_is_read_at_call_time(env, app_module, make_client):
    env.set_env("PRIMARY_DB_FIELD", "email")
    env.set_env("PRIMARY_OIDC_FIELD", "email")
    assert oidc_login(make_client, app_module)[1] == "bob"
    env.set_env("PRIMARY_OIDC_FIELD", "alt_email")
    assert oidc_login(make_client, app_module)[1] == "carol"


def test_primary_db_field_is_read_at_call_time(env, app_module, make_client):
    env.set_env("PRIMARY_OIDC_FIELD", "preferred_username")
    env.set_env("PRIMARY_DB_FIELD", "email")
    assert oidc_login(make_client, app_module)[1] is None  # "alice" is no one's email
    env.set_env("PRIMARY_DB_FIELD", "username")
    assert oidc_login(make_client, app_module)[1] == "alice"


def test_secondary_oidc_field_is_read_at_call_time(env, app_module, make_client):
    # PRIMARY_* are unset, so only the secondary fields can match.
    env.set_env("SECONDARY_DB_FIELD", "username")
    env.set_env("SECONDARY_OIDC_FIELD", "preferred_username")
    assert oidc_login(make_client, app_module)[1] == "alice"
    env.set_env("SECONDARY_OIDC_FIELD", "nickname")
    assert oidc_login(make_client, app_module)[1] == "carol"


def test_secondary_db_field_is_read_at_call_time(env, app_module, make_client):
    env.set_env("SECONDARY_OIDC_FIELD", "nickname")
    env.set_env("SECONDARY_DB_FIELD", "email")
    assert oidc_login(make_client, app_module)[1] is None  # "carol" is no one's email
    env.set_env("SECONDARY_DB_FIELD", "username")
    assert oidc_login(make_client, app_module)[1] == "carol"


def test_enable_auto_registration_is_read_at_call_time(env, app_module, make_client):
    newcomer = {"email": "new@example.com", "preferred_username": "newcomer", "name": "New Comer"}
    env.set_env("PRIMARY_OIDC_FIELD", "email")
    env.set_env("PRIMARY_DB_FIELD", "email")

    response, username = oidc_login(make_client, app_module, newcomer)
    assert is_redirect_to(response, "/login") and username is None
    assert "newcomer" not in [u["username"] for u in env.users()]

    env.set_env("ENABLE_AUTO_REGISTRATION", "true")
    response, username = oidc_login(make_client, app_module, newcomer)
    assert is_redirect_to(response, "/setup_profile") and username == "newcomer"
    assert "newcomer" in [u["username"] for u in env.users()]


# Default login -------------------------------------------------------------------

def test_enable_default_login_is_read_at_call_time(client, env):
    def title():
        page = client.get("/login", headers={"Accept-Language": "en"}).get_data(as_text=True)
        return page[page.index("<title>"):page.index("</title>")]

    assert title() == "<title>Login"
    env.set_env("ENABLE_DEFAULT_LOGIN", "false")
    assert title() == "<title>OIDC Login Only"
    login(client, "alice")
    assert session_username(client) is None


# /setup_oidc form values ----------------------------------------------------------

@pytest.mark.parametrize("key", [
    "OIDC_CLIENT_ID", "OIDC_CLIENT_SECRET", "OIDC_SERVER_METADATA_URL", "OIDC_LOGOUT_URL",
    "PRIMARY_OIDC_FIELD", "SECONDARY_OIDC_FIELD",
])
def test_setup_oidc_form_shows_current_text_value(client, env, key):
    login(client, "admin")
    env.set_env(key, "first-value")
    assert 'value="first-value"' in client.get("/setup_oidc").get_data(as_text=True)
    env.set_env(key, "second-value")
    assert 'value="second-value"' in client.get("/setup_oidc").get_data(as_text=True)


@pytest.mark.parametrize("key, first, second", [
    ("PRIMARY_DB_FIELD", "username", "full_name"),
    ("SECONDARY_DB_FIELD", "email", "full_name"),
    ("ENABLE_AUTO_REGISTRATION", "true", "false"),
    ("ENABLE_DEFAULT_LOGIN", "false", "true"),
])
def test_setup_oidc_form_shows_current_select_value(client, env, key, first, second):
    login(client, "admin")

    def selected(value):
        page = client.get("/setup_oidc").get_data(as_text=True)
        select = page[page.index(f'name="{key}"'):]
        select = select[:select.index("</select>")]
        return f'<option value="{value}" selected>' in select

    env.set_env(key, first)
    assert selected(first) and not selected(second)
    env.set_env(key, second)
    assert selected(second) and not selected(first)


# OIDC robustness ------------------------------------------------------------------

def test_oidc_matching_tolerates_null_fields(env, app_module, make_client):
    """A user whose matched field is null used to crash /auth (None.lower())."""
    env.update_user("bob", email=None)
    env.set_env("PRIMARY_OIDC_FIELD", "email")
    env.set_env("PRIMARY_DB_FIELD", "email")
    response, username = oidc_login(make_client, app_module, {"email": "carol@example.com"})
    assert username == "carol"


@pytest.mark.parametrize("preferred_username", ["alice", "ALICE", "shared_smith"])
def test_auto_registration_refuses_existing_username(env, app_module, make_client, preferred_username):
    """An unmatched identity whose preferred_username belongs to an existing
    account must not be logged in as that account, nor create a duplicate."""
    env.set_env("ENABLE_AUTO_REGISTRATION", "true")
    env.set_env("PRIMARY_OIDC_FIELD", "email")
    env.set_env("PRIMARY_DB_FIELD", "email")
    env.set_env("SECONDARY_OIDC_FIELD", "nickname")
    env.set_env("SECONDARY_DB_FIELD", "username")
    before = env.users()
    response, username = oidc_login(make_client, app_module,
                                    {"email": "intruder@example.com", "preferred_username": preferred_username})
    assert is_redirect_to(response, "/login") and username is None
    assert env.users() == before


@pytest.mark.parametrize("preferred_username", [None, "", "   "])
def test_auto_registration_refuses_missing_username(env, app_module, make_client, preferred_username):
    env.set_env("ENABLE_AUTO_REGISTRATION", "true")
    env.set_env("PRIMARY_OIDC_FIELD", "email")
    env.set_env("PRIMARY_DB_FIELD", "email")
    before = env.users()
    response, username = oidc_login(make_client, app_module,
                                    {"email": "new@example.com", "preferred_username": preferred_username})
    assert is_redirect_to(response, "/login") and username is None
    assert env.users() == before


OIDC_FORM = {
    "OIDC_CLIENT_ID": "client", "OIDC_CLIENT_SECRET": "secret",
    "OIDC_SERVER_METADATA_URL": "https://idp.example/.well-known/openid-configuration",
    "OIDC_LOGOUT_URL": "https://idp.example/logout", "PRIMARY_OIDC_FIELD": "email",
    "SECONDARY_OIDC_FIELD": "preferred_username", "PRIMARY_DB_FIELD": "email",
    "SECONDARY_DB_FIELD": "username", "ENABLE_AUTO_REGISTRATION": "false", "ENABLE_DEFAULT_LOGIN": "true",
}


def test_setup_oidc_warns_that_client_changes_need_a_restart(client):
    login(client, "admin")
    client.get("/dashboard")  # consume the login flash message

    def categories(form):
        assert is_redirect_to(client.post("/setup_oidc", data=form), "/setup_oidc")
        with client.session_transaction() as sess:
            return [category for category, _ in sess.pop("_flashes", [])]

    assert categories(OIDC_FORM) == ["success", "warning"]
    assert categories(OIDC_FORM) == ["success"]  # nothing that needs a restart changed
    assert categories(dict(OIDC_FORM, OIDC_LOGOUT_URL="https://idp.example/bye")) == ["success"]
    assert categories(dict(OIDC_FORM, OIDC_CLIENT_SECRET="rotated")) == ["success", "warning"]
