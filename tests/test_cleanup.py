"""Purge of old gift ideas (/rundl, admin page) and the buyer email sent on deletion."""
from datetime import datetime, timedelta
from unittest import mock

import pytest

from smoke_helpers import login


def _ago(days):
    return (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")


@pytest.fixture
def old_purchases(env):
    """Idea 2 bought 40 days ago, idea 3 bought 10 days ago."""
    env.update_idea(2, date_bought=_ago(40))
    env.update_idea(3, bought_by="alice", date_bought=_ago(10))


def _ids(env):
    return {idea["gift_idea_id"] for idea in env.ideas()}


def test_rundl_purges_bought_ideas_older_than_delete_days(client, env, old_purchases):
    response = client.get("/rundl")
    assert response.status_code == 200
    assert _ids(env) == {1, 3, 4, 5}


def test_rundl_reads_delete_days_at_call_time(client, env, old_purchases):
    env.set_env("DELETE_DAYS", "5")
    client.get("/rundl")
    assert _ids(env) == {1, 4, 5}


@pytest.mark.parametrize("value", ["", "abc", "0", "-3", "1000000"])
def test_rundl_falls_back_to_default_delete_days(client, env, old_purchases, value):
    """An empty or invalid DELETE_DAYS used to make the purge read the .env
    path as a number of days. The default (30 days) applies instead."""
    env.set_env("DELETE_DAYS", value)
    response = client.get("/rundl")
    assert response.status_code == 200
    assert _ids(env) == {1, 3, 4, 5}


def test_rundl_falls_back_to_default_when_delete_days_is_missing(client, env, old_purchases):
    env.env_file.write_text("\n".join(line for line in env.env_file.read_text().splitlines()
                                      if not line.startswith("DELETE_DAYS=")))
    client.get("/rundl")
    assert _ids(env) == {1, 3, 4, 5}


@pytest.mark.parametrize("bad_date", ["02/01/2026", "yesterday", 12345])
def test_purge_skips_ideas_with_bad_dates(client, env, old_purchases, bad_date):
    """One malformed date used to abort the whole purge (nothing deleted)."""
    env.update_idea(4, bought_by="bob", date_bought=bad_date)
    client.get("/rundl")
    assert _ids(env) == {1, 3, 4, 5}  # idea 2 purged, idea 4 kept


def test_admin_purge_skips_ideas_with_bad_dates(client, env, old_purchases):
    env.update_idea(4, bought_by="bob", date_bought="02/01/2026")
    login(client, "admin")
    response = client.post("/delete_old_gift_ideas", data={"bought_only": "on", "age_filter": "on", "days": "30"})
    assert response.status_code == 200
    assert _ids(env) == {1, 3, 4, 5}


@pytest.mark.parametrize("path", ["/delete_old_gift_ideas", "/change_delete_days"])
def test_admin_pages_show_default_when_delete_days_is_invalid(client, env, path):
    env.set_env("DELETE_DAYS", "abc")
    login(client, "admin")
    response = client.get(path)
    assert response.status_code == 200
    assert 'value="30"' in response.get_data(as_text=True)


@pytest.mark.parametrize("days", ["0", "-1", "abc", "1000000", "²"])
def test_change_delete_days_refuses_invalid_values(client, env, days):
    login(client, "admin")
    client.post("/change_delete_days", data={"days": days})
    assert "DELETE_DAYS='30'" in env.env_file.read_text()


def test_change_delete_days_saves_value(client, env):
    login(client, "admin")
    client.post("/change_delete_days", data={"days": "12"})
    assert "DELETE_DAYS='12'" in env.env_file.read_text()


def test_delete_idea_proceeds_when_mailjet_fails(client, env, mailer_module):
    """Deleting a bought idea emails the buyer first; a Mailjet error used to
    abort the deletion with a 500."""
    env.set_env("MAILJET_API_KEY", "key")
    env.set_env("MAILJET_API_SECRET", "secret")
    login(client, "bob")
    with mock.patch.object(mailer_module, "Client") as mailjet_client:
        mailjet_client.return_value.send.create.side_effect = ConnectionError("mailjet down")
        assert client.delete("/delete_idea/2").status_code == 204
    mailjet_client.return_value.send.create.assert_called_once()
    assert 2 not in _ids(env)
