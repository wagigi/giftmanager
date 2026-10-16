"""Runtime-editable settings are read from DATA_DIR/.env at call time.

Each test edits the test .env (with the same writer as the admin pages) after
`app` was imported, and checks that the new value applies without re-importing
anything. os.environ is not touched here (except for an unrelated test key in
the environment-fallback test): the conftest removed these keys from it before
import, so only the .env file can supply them.
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
    newcomer = {"email": "new@example.com", "preferred_username": " newcomer ", "name": "New Comer"}  # stored stripped
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


def test_oidc_cannot_log_in_as_shared_list(env, app_module, make_client):
    """/login refuses shared-list accounts; OIDC matching skips them too."""
    env.set_env("SECONDARY_OIDC_FIELD", "preferred_username")
    env.set_env("SECONDARY_DB_FIELD", "username")
    response, username = oidc_login(make_client, app_module, {"preferred_username": "shared_smith"})
    assert is_redirect_to(response, "/login") and username is None


@pytest.mark.parametrize("preferred_username", ["alice", "ALICE", " alice ", "shared_smith"])
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


def test_setup_oidc_warns_that_client_changes_need_a_restart(client, app_module, monkeypatch):
    """The warning compares the saved values with the ones the OAuth client was
    registered with at startup (empty in the test .env), so it is repeated
    until the app is restarted."""
    login(client, "admin")
    client.get("/dashboard")  # consume the login flash message

    def categories(form):
        assert is_redirect_to(client.post("/setup_oidc", data=form), "/setup_oidc")
        with client.session_transaction() as sess:
            return [category for category, _ in sess.pop("_flashes", [])]

    assert categories(OIDC_FORM) == ["success", "warning"]
    assert categories(OIDC_FORM) == ["success", "warning"]  # saved again without a restart

    # As if restarted with the saved values
    monkeypatch.setattr(app_module, "OIDC_STARTUP_SETTINGS",
                        {key: OIDC_FORM[key] for key in app_module.OIDC_STARTUP_SETTINGS})
    assert categories(OIDC_FORM) == ["success"]
    assert categories(dict(OIDC_FORM, OIDC_LOGOUT_URL="https://idp.example/bye")) == ["success"]
    assert categories(dict(OIDC_FORM, OIDC_CLIENT_SECRET="rotated")) == ["success", "warning"]


# read_env_variable parsing (python-dotenv) ------------------------------------------

@pytest.fixture
def config_module(env):
    import sys
    return sys.modules["config"]


@pytest.mark.parametrize("line, expected", [
    ("KEY=plain", "plain"),
    ("KEY='single quoted'", "single quoted"),
    ('KEY="double quoted"', "double quoted"),
    ("KEY=value # inline comment", "value"),
    ("KEY='value # not a comment'", "value # not a comment"),
    (r"KEY='it\'s'", "it's"),
    (r"KEY='back\\slash'", "back\\slash"),
    ("KEY='${HOME}'", "${HOME}"),  # no variable expansion
    ("export KEY=exported", "exported"),
])
def test_read_env_variable_parses_like_python_dotenv(env, config_module, line, expected):
    env.env_file.write_text(env.env_file.read_text() + line + "\n")
    assert config_module.read_env_variable("KEY") == expected


def test_read_env_variable_last_duplicate_wins(env, config_module):
    env.env_file.write_text(env.env_file.read_text() + "KEY=first\nKEY=second\n")
    assert config_module.read_env_variable("KEY") == "second"


@pytest.mark.parametrize("line", ["KEY=", "KEY=''", "KEY"])
def test_read_env_variable_empty_value_returns_default(env, config_module, line):
    env.env_file.write_text(env.env_file.read_text() + line + "\n")
    assert config_module.read_env_variable("KEY", "fallback") == "fallback"
    assert config_module.read_env_variable("KEY") is None


def test_read_env_variable_missing_key_falls_back_to_environment(env, config_module, monkeypatch):
    assert config_module.read_env_variable("GM_TEST_KEY", "fallback") == "fallback"
    monkeypatch.setenv("GM_TEST_KEY", "from-environ")
    assert config_module.read_env_variable("GM_TEST_KEY", "fallback") == "from-environ"


def test_read_env_variable_without_env_file(env, config_module):
    env.env_file.unlink()
    assert config_module.read_env_variable("GM_TEST_KEY", "fallback") == "fallback"


# Admin pages write through set_key: values round-trip -------------------------------

TRICKY = "it's a \\ test ${HOME} # not a comment \"quoted\""


def test_setup_oidc_value_round_trips(client, env, config_module):
    login(client, "admin")
    client.post("/setup_oidc", data=dict(OIDC_FORM, OIDC_CLIENT_SECRET=TRICKY, OIDC_LOGOUT_URL=TRICKY))
    assert config_module.read_env_variable("OIDC_CLIENT_SECRET") == TRICKY
    assert config_module.read_env_variable("OIDC_LOGOUT_URL") == TRICKY
    page = client.get("/setup_oidc").get_data(as_text=True)
    assert 'value="it&#39;s a \\ test ${HOME} # not a comment &#34;quoted&#34;"' in page


def test_edit_login_message_round_trips(client, env, config_module, make_client):
    login(client, "admin")
    client.post("/edit_login_message", data={"login_message": TRICKY})
    assert config_module.read_env_variable("LOGIN_PAGE_MESSAGE") == TRICKY
    assert "it&#39;s a \\ test ${HOME} # not a comment &#34;quoted&#34;" in make_client().get("/login").get_data(as_text=True)

    # Saved again: the existing line is replaced, not duplicated
    client.post("/edit_login_message", data={"login_message": "Second message"})
    assert config_module.read_env_variable("LOGIN_PAGE_MESSAGE") == "Second message"
    assert env.env_file.read_text().count("LOGIN_PAGE_MESSAGE=") == 1


def test_edit_login_message_adds_missing_key(client, env, config_module):
    """The old writer only replaced an existing LOGIN_PAGE_MESSAGE line, so on a
    .env without one the new message was silently dropped."""
    assert "LOGIN_PAGE_MESSAGE" not in env.env_file.read_text()
    login(client, "admin")
    client.post("/edit_login_message", data={"login_message": "Hello family"})
    assert config_module.read_env_variable("LOGIN_PAGE_MESSAGE") == "Hello family"


def test_edit_email_settings_round_trips_and_keeps_blank_fields(client, env, config_module):
    env.set_env("MAILJET_API_KEY", "old-key")
    login(client, "admin")
    client.post("/edit_email_settings", data={"MAILJET_API_KEY": "", "MAILJET_API_SECRET": TRICKY,
                                              "SYSTEM_EMAIL": "o'brien@example.com"})
    assert config_module.read_env_variable("MAILJET_API_KEY") == "old-key"  # blank: unchanged
    assert config_module.read_env_variable("MAILJET_API_SECRET") == TRICKY
    assert config_module.read_env_variable("SYSTEM_EMAIL") == "o'brien@example.com"


def test_read_env_variable_reads_legacy_unescaped_quotes(env, config_module, client, make_client):
    """Older versions wrote LOGIN_PAGE_MESSAGE='...' without escaping, which
    python-dotenv cannot parse. Such lines keep their former value until saved again."""
    env.env_file.write_text(env.env_file.read_text() + "LOGIN_PAGE_MESSAGE='Contactez l'administrateur'\n")
    assert config_module.read_env_variable("LOGIN_PAGE_MESSAGE") == "Contactez l'administrateur"
    assert config_module.read_env_variable("REORDERING") == "true"  # the other lines still parse
    assert "Contactez l&#39;administrateur" in make_client().get("/login").get_data(as_text=True)

    login(client, "admin")
    client.post("/edit_login_message", data={"login_message": "C'est réparé"})
    assert config_module.read_env_variable("LOGIN_PAGE_MESSAGE") == "C'est réparé"
    # The unparsable line was replaced, not kept next to the new one
    assert "l'administrateur" not in env.env_file.read_text()
    assert env.env_file.read_text().count("LOGIN_PAGE_MESSAGE=") == 1


def test_set_env_variable_keeps_multiline_and_other_lines(env, config_module):
    env.env_file.write_text("A='x'\nMULTI='line1\nline2'\nBROKEN='it's'\nKEY='old'\n")
    config_module.set_env_variable("KEY", "new")
    assert env.env_file.read_text() == "A='x'\nMULTI='line1\nline2'\nBROKEN='it's'\nKEY='new'\n"
    config_module.set_env_variable("BROKEN", "it's")
    assert config_module.read_env_variable("BROKEN") == "it's"
    assert config_module.read_env_variable("MULTI") == "line1\nline2"
    assert env.env_file.read_text().count("BROKEN=") == 1


def test_read_env_variable_does_not_log_for_legacy_lines(env, config_module, caplog):
    env.env_file.write_text(env.env_file.read_text() + "LOGIN_PAGE_MESSAGE='l'admin'\n")
    with caplog.at_level("WARNING"):
        config_module.read_env_variable("LOGIN_PAGE_MESSAGE")
    assert not [r for r in caplog.records if r.name.startswith("dotenv")]


def test_login_oidc_button_follows_the_registered_client(client, app_module, monkeypatch):
    """The OIDC button only shows when the OAuth client was registered with a
    client ID at startup, even if os.environ was reloaded since."""
    monkeypatch.setenv("OIDC_CLIENT_ID", "reloaded-but-not-registered")
    assert "/login_oidc" not in client.get("/login").get_data(as_text=True)
    monkeypatch.setitem(app_module.OIDC_STARTUP_SETTINGS, "OIDC_CLIENT_ID", "registered")
    assert "/login_oidc" in client.get("/login").get_data(as_text=True)
