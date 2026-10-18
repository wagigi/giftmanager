"""Missing idea dates filled in at startup, and the idea age shown on the idea pages."""
import importlib
import sys
from datetime import date, datetime, timedelta
from unittest import mock

import pytest

from smoke_helpers import SHARE_TOKEN, login


def _ago(days):
    return (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")


@pytest.fixture
def idea_dates(env):
    """The idea_dates module loaded by this test's app."""
    return sys.modules["idea_dates"]


@pytest.fixture
def undated(env):
    """Ideas from older versions: 1 without date_added, 2 bought by bob without any date."""
    ideas = env.ideas()
    for idea in ideas:
        if idea["gift_idea_id"] in (1, 2):
            del idea["date_added"]
        if idea["gift_idea_id"] == 2:
            del idea["date_bought"]
    env.write_ideas(ideas)


def test_migration_fills_and_flags_missing_dates(env, idea_dates, undated):
    before = datetime.now().replace(microsecond=0)
    assert idea_dates.migrate_ideas_file(env.ideas_file) == 2

    one, two, three = env.idea(1), env.idea(2), env.idea(3)
    assert one["date_added_unknown"] is True and "date_bought" not in one  # not bought: no purchase date
    assert two["date_added_unknown"] is True and two["date_bought_unknown"] is True
    assert datetime.strptime(two["date_bought"], "%Y-%m-%d %H:%M:%S") >= before
    # Ideas with their dates are left alone
    assert three["date_added"] == "2026-01-01 10:00:00" and "date_added_unknown" not in three

    assert idea_dates.migrate_ideas_file(env.ideas_file) == 0  # idempotent


def test_migration_keeps_the_file_permissions(env, idea_dates, undated):
    env.ideas_file.chmod(0o644)
    assert idea_dates.migrate_ideas_file(env.ideas_file) == 2
    assert env.ideas_file.stat().st_mode & 0o777 == 0o644


def test_migration_runs_when_the_app_starts(env, undated):
    importlib.reload(env.module)  # same DATA_DIR: runs app.py's startup code again on the undated ideas
    assert env.idea(1)["date_added_unknown"] is True
    assert env.idea(2)["date_bought_unknown"] is True


def test_empty_bought_by_gets_no_purchase_date(env, idea_dates):
    """bought_by "" (as on the idea written on first start) is not a purchase."""
    ideas = [{"gift_idea_id": 1, "user_id": "alice", "added_by": "alice", "bought_by": ""}]
    assert idea_dates.backfill_missing_dates(ideas) == 1
    assert ideas[0]["date_added_unknown"] is True and "date_bought" not in ideas[0]


def test_backfilled_purchase_is_purged_after_delete_days(client, env, idea_dates, undated):
    """Ideas bought before date_bought existed were never purged: they now age from the migration date."""
    ideas = env.ideas()
    idea_dates.backfill_missing_dates(ideas, now=datetime.now() - timedelta(days=40))
    env.write_ideas(ideas)
    client.get("/rundl")
    assert 2 not in {idea["gift_idea_id"] for idea in env.ideas()}


def test_new_purchase_date_replaces_the_unknown_flag(client, env, idea_dates, undated):
    idea_dates.migrate_ideas_file(env.ideas_file)
    login(client, "bob")
    client.post("/mark_as_not_bought/2")
    idea = env.idea(2)
    assert "date_bought" not in idea and "date_bought_unknown" not in idea
    client.post("/mark_as_bought/2")
    idea = env.idea(2)
    assert idea["date_bought"] and "date_bought_unknown" not in idea


@pytest.mark.parametrize("added, unknown, label", [
    (date(2026, 10, 18), False, "Today"),
    (date(2026, 10, 17), False, "1 day"),
    (date(2026, 9, 19), False, "29 days"),
    (date(2026, 9, 18), False, "1 month"),
    (date(2026, 9, 30), False, "18 days"),
    (date(2026, 9, 20), False, "28 days"),
    (date(2025, 10, 19), False, "11 months"),
    (date(2024, 10, 18), False, "2 years"),
    (date(2026, 10, 18), True, "Date unknown"),
    (date(2026, 10, 15), True, "More than 3 days"),
    (date(2026, 7, 1), True, "More than 3 months"),
    (date(2025, 1, 1), True, "More than 1 year"),
])
def test_idea_age_labels(app_module, idea_dates, added, unknown, label):
    idea = {"date_added": f"{added:%Y-%m-%d} 12:00:00"}
    if unknown:
        idea["date_added_unknown"] = True
    with app_module.app.test_request_context(headers={"Accept-Language": "en"}):
        assert idea_dates.idea_age(idea, today=date(2026, 10, 18)) == {"label": label, "unknown": unknown}


def test_idea_age_is_translated(app_module, idea_dates):
    with app_module.app.test_request_context(headers={"Accept-Language": "fr"}):
        assert idea_dates.idea_age({"date_added": "2026-10-01 12:00:00", "date_added_unknown": True},
                                   today=date(2026, 10, 18))["label"] == "Plus de 17 jours"
        assert idea_dates.idea_age({"date_added": "2026-10-18 12:00:00"}, today=date(2026, 10, 18))["label"] == "Aujourd'hui"


@pytest.mark.parametrize("added, today, label", [
    (date(2026, 1, 31), date(2026, 3, 1), "29 days"),  # a calendar month, but only 29 days
    (date(2026, 2, 28), date(2026, 3, 28), "28 days"),
    (date(2026, 1, 31), date(2026, 3, 2), "1 month"),
])
def test_idea_age_around_month_ends(app_module, idea_dates, added, today, label):
    with app_module.app.test_request_context(headers={"Accept-Language": "en"}):
        assert idea_dates.idea_age({"date_added": f"{added:%Y-%m-%d} 12:00:00"}, today=today)["label"] == label


@pytest.mark.parametrize("value", [None, "", "18/10/2026"])
def test_idea_age_without_readable_date(app_module, idea_dates, value):
    with app_module.app.test_request_context():
        assert idea_dates.idea_age({"date_added": value}) is None


@pytest.mark.parametrize("username, path", [
    ("bob", "/user_gift_ideas/alice"),
    ("bob", "/table_view"),
    ("alice", "/my_ideas"),
    ("bob", "/bought_items"),
    (None, f"/shared/{SHARE_TOKEN}"),
])
def test_pages_show_the_idea_age(client, env, username, path):
    env.update_idea(1, date_added=_ago(5))
    env.update_idea(2, date_added=_ago(5))
    client.get("/set_language/en")
    if username:
        login(client, username)
    page = client.get(path).get_data(as_text=True)
    assert 'class="idea-age"' in page
    assert "5 days" in page


def test_unknown_date_is_explained_on_hover(client, env):
    env.update_idea(1, date_added=_ago(12), date_added_unknown=True)
    client.get("/set_language/en")
    login(client, "bob")
    page = client.get("/user_gift_ideas/alice").get_data(as_text=True)
    assert "More than 12 days" in page
    assert "before the app started recording dates" in page


def test_demo_placeholder_stays_undated(env, idea_dates):
    """The seeded "dont delete" idea has no date, which keeps the age-based admin purge from deleting it."""
    ideas = [{"gift_idea_id": 1, "user_id": "demo", "added_by": "demo", "bought_by": ""}]
    assert idea_dates.backfill_missing_dates(ideas) == 0
    assert "date_added" not in ideas[0]


@pytest.mark.parametrize("content", ["not json", '{"a": 1}', "[null]"])
def test_migration_never_stops_the_app(env, idea_dates, content):
    env.ideas_file.write_text(content)
    assert idea_dates.migrate_ideas_file(env.ideas_file) == 0
    assert env.ideas_file.read_text() == content


def test_migration_keeps_the_file_when_the_write_fails(env, idea_dates, undated, monkeypatch):
    before = env.ideas_file.read_text()
    monkeypatch.setattr(idea_dates.json, "dump", mock.Mock(side_effect=OSError("disk full")))
    assert idea_dates.migrate_ideas_file(env.ideas_file) == 0
    assert env.ideas_file.read_text() == before
    assert [p.name for p in env.data_dir.iterdir() if p.name.startswith(".ideas.")] == []
