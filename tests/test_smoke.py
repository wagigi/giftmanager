"""Smoke tests freezing the current behavior of the main routes.

These tests describe what the app does today, not what it should do. When a
test documents questionable behavior, the docstring says so.
"""
from datetime import datetime, timedelta
from unittest import mock

import pytest

from smoke_helpers import EXPIRED_TOKEN, SHARE_TOKEN, flashes, is_redirect_to, login, session_username


# 1. Login ---------------------------------------------------------------------

def test_login_page_renders(client):
    response = client.get("/login")
    assert response.status_code == 200
    assert b'name="username"' in response.data
    assert b'name="password"' in response.data


def test_login_with_good_password_redirects_to_dashboard(client):
    response = login(client, "alice")
    assert is_redirect_to(response, "/dashboard")
    assert session_username(client) == "alice"


def test_login_is_case_insensitive_on_username(client):
    response = login(client, "ALICE", "alicepass")
    assert is_redirect_to(response, "/dashboard")
    assert session_username(client) == "alice"


def test_login_with_wrong_password_does_not_open_session(client):
    response = login(client, "alice", "wrong")
    assert response.status_code == 200
    assert session_username(client) is None


def test_login_with_unknown_user_does_not_open_session(client):
    response = login(client, "nobody", "whatever")
    assert response.status_code == 200
    assert session_username(client) is None


def test_shared_list_account_cannot_log_in(client):
    response = login(client, "shared_smith")  # correct password, refused by the shared_list guard
    assert response.status_code == 200
    assert session_username(client) is None


def test_logout_clears_session(client):
    login(client, "alice")
    response = client.get("/logout")
    assert is_redirect_to(response, "/login")
    assert session_username(client) is None


# 2. Anonymous access ------------------------------------------------------------

@pytest.mark.parametrize("path", ["/dashboard", "/my_ideas", "/bought_items", "/user_gift_ideas/bob", "/add_idea/bob"])
def test_anonymous_is_redirected_to_login(client, path):
    response = client.get(path)
    assert is_redirect_to(response, "/login")


def test_index_redirects_anonymous_to_login(client):
    assert is_redirect_to(client.get("/"), "/login")


# 3. Admin routes -----------------------------------------------------------------

ADMIN_PAGES = ["/admin", "/users", "/families", "/manage_guest_users", "/secret_santa", "/setup_advanced"]


@pytest.mark.parametrize("path", ADMIN_PAGES)
def test_normal_user_cannot_open_admin_pages(client, path):
    login(client, "alice")
    client.get("/dashboard")  # consume the login flash message
    response = client.get(path)
    assert is_redirect_to(response, "/dashboard")
    assert [category for category, _ in flashes(client)] == ["danger"]


@pytest.mark.parametrize("path", ["/admin", "/users"])
def test_anonymous_cannot_open_admin_pages(client, path):
    assert is_redirect_to(client.get(path), "/login")


@pytest.mark.parametrize("path", ADMIN_PAGES)
def test_admin_can_open_admin_pages(client, path):
    login(client, "admin")
    assert client.get(path).status_code == 200


# 4. Adding an idea --------------------------------------------------------------

def test_add_idea_page_renders(client):
    login(client, "alice")
    response = client.get("/add_idea/bob")
    assert response.status_code == 200


def test_add_idea_for_another_user_is_saved(client, env):
    login(client, "alice")
    response = client.post(
        "/add_idea/bob",
        data={"user": "bob", "name": "Board game", "description": "Any", "link": "", "value": "25", "imagePath": ""},
    )
    assert is_redirect_to(response, "/user_gift_ideas/bob")

    new = [i for i in env.ideas() if i["gift_name"] == "Board game"]
    assert len(new) == 1
    idea = new[0]
    assert idea["user_id"] == "bob"
    assert idea["added_by"] == "alice"
    assert idea["bought_by"] is None
    assert idea["value"] == "25"
    assert idea["gift_idea_id"] == 6  # max existing id + 1


# 5. Mark as bought / not bought --------------------------------------------------

def test_mark_as_bought_then_not_bought(client, env):
    """CURRENT BEHAVIOR (questionable): /mark_as_bought redirects to the buyer's
    own /user_gift_ideas page (which bounces to /my_ideas), not to the
    recipient's list. The UI calls it with fetch(), so the redirect is unused."""
    login(client, "alice")

    response = client.post("/mark_as_bought/3")
    assert is_redirect_to(response, "/user_gift_ideas/alice")
    idea = env.idea(3)
    assert idea["bought_by"] == "alice"
    assert idea["date_bought"]

    response = client.post("/mark_as_not_bought/3")
    assert response.status_code == 204
    idea = env.idea(3)
    assert not idea["bought_by"]
    assert "date_bought" not in idea


def test_mark_as_bought_does_not_overwrite_existing_buyer(client, env, make_client):
    login(client, "alice")
    client.post("/mark_as_bought/3")
    other = make_client()
    login(other, "admin")
    other.post("/mark_as_bought/3")
    assert env.idea(3)["bought_by"] == "alice"
    assert [category for category, _ in flashes(other)] == ["login_success", "warning"]


def test_only_the_buyer_can_mark_as_not_bought(client, env, make_client):
    login(client, "alice")
    client.post("/mark_as_bought/3")
    other = make_client()
    login(other, "admin")  # sees everyone, so only the buyer rule can refuse
    other.post("/mark_as_not_bought/3")  # always answers 204, refused or not
    assert env.idea(3)["bought_by"] == "alice"
    assert [category for category, _ in flashes(other)] == ["login_success", "danger"]


def test_mark_as_bought_ignores_families(client, env):
    """CURRENT BEHAVIOR (likely a visibility hole): /mark_as_bought does not
    check families, so alice (Smith) can buy carol's (Jones) idea by id."""
    login(client, "alice")
    client.post("/mark_as_bought/4")
    assert env.idea(4)["bought_by"] == "alice"


# Deleting an idea --------------------------------------------------------------

def test_delete_own_idea(client, env):
    login(client, "alice")
    assert client.delete("/delete_idea/5").status_code == 204
    assert 5 not in [i["gift_idea_id"] for i in env.ideas()]


def test_delete_bought_idea_without_mailjet_keys(client, env):
    """The recipient may delete an idea someone else added. The buyer email is
    skipped because the Mailjet keys are empty (no network call)."""
    login(client, "alice")
    with mock.patch.object(env.module, "Client") as mailjet_client:
        assert client.delete("/delete_idea/2").status_code == 204
    mailjet_client.assert_not_called()
    assert 2 not in [i["gift_idea_id"] for i in env.ideas()]


def test_delete_idea_of_someone_else_is_refused(client, env):
    login(client, "carol")
    assert client.delete("/delete_idea/1").status_code == 403
    assert 1 in [i["gift_idea_id"] for i in env.ideas()]


@pytest.mark.xfail(
    reason="Bug: /delete_idea reads idea['user_id'] before checking that the idea exists, "
           "so an unknown id raises TypeError (HTTP 500) instead of answering 403",
    raises=TypeError,
    strict=True,
)
def test_delete_unknown_idea(client):
    login(client, "alice")
    assert client.delete("/delete_idea/999").status_code == 403


# 6. Surprise rule ----------------------------------------------------------------

def test_buyer_sees_purchase_on_recipient_list(client):
    """Sanity check for the tests below: the bought idea and its buyer are
    visible to other users (admin has no family, so sees everyone)."""
    login(client, "admin")
    client.get("/set_language/en")
    page = client.get("/user_gift_ideas/alice").get_data(as_text=True)
    assert "Secret telescope" in page
    assert "Purchased by: Bob Smith" in page


def test_recipient_my_ideas_hides_buyer_and_bought_idea(client):
    """Idea 2 is for alice, added and bought by bob. /my_ideas only lists ideas
    alice added herself, so neither the idea nor bob shows up. (Ideas alice
    added herself and that get bought are covered by the before/after test.)"""
    login(client, "alice")
    response = client.get("/my_ideas")
    assert response.status_code == 200
    page = response.get_data(as_text=True)
    assert "Alice own idea" in page
    assert "Secret telescope" not in page
    assert "Bob Smith" not in page
    assert "2026-01-02" not in page  # date_bought


@pytest.mark.xfail(
    reason="Bug (surprise rule): when the recipient POSTs /mark_as_bought on her own idea "
           "that is already bought, the warning flash names the buyer (the UI offers no button "
           "for this, it takes a hand-crafted POST)",
    raises=AssertionError,
    strict=True,
)
def test_recipient_mark_as_bought_does_not_reveal_buyer(client, env):
    login(client, "alice")
    client.get("/dashboard")  # consume the login flash message
    client.post("/mark_as_bought/2")
    assert env.idea(2)["bought_by"] == "bob"
    assert not any("bob" in message.lower() for _, message in flashes(client))


def test_recipient_self_list_redirects_to_my_ideas(client):
    login(client, "alice")
    assert is_redirect_to(client.get("/user_gift_ideas/alice"), "/my_ideas")


def test_recipient_pages_do_not_change_when_own_idea_is_bought(client, env, make_client):
    """Buying one of alice's own ideas must not change anything alice can see
    on /my_ideas and /dashboard. (bob is in alice's family, so his name is on
    the dashboard anyway; what matters is that nothing reveals the purchase.)"""
    login(client, "alice")
    client.get("/dashboard")  # consume the login flash message
    before = {path: client.get(path).get_data(as_text=True) for path in ("/my_ideas", "/dashboard")}

    buyer = make_client()
    login(buyer, "bob")
    buyer.post("/mark_as_bought/1")
    idea = env.idea(1)
    assert idea["bought_by"] == "bob"

    for path, page in before.items():
        after = client.get(path).get_data(as_text=True)
        assert after == page, f"{path} changed after alice's idea was bought"

    my_ideas = client.get("/my_ideas").get_data(as_text=True)
    assert "Alice own idea" in my_ideas
    assert "Bob Smith" not in my_ideas
    assert idea["date_bought"][:10] not in my_ideas


def test_recipient_table_view_hides_bought_marker(client, make_client):
    """CURRENT BEHAVIOR (questionable): /table_view lists every idea for alice,
    including the ones others added for her (unlike /my_ideas), so she sees
    the surprise idea's name. It does hide the bought marker in her own
    column. Idea 2 is the only bought idea in the fixtures."""
    login(client, "alice")
    page = client.get("/table_view").get_data(as_text=True)
    assert "Secret telescope" in page
    assert "fa-check-circle" not in page
    assert "Bob Smith" in page  # bob's column header, not a buyer marker

    other = make_client()
    login(other, "carol")
    assert other.get("/table_view").get_data(as_text=True).count("fa-check-circle") == 1


# 7. Family visibility ------------------------------------------------------------

def test_dashboard_shows_same_family_and_hides_other_family(client):
    login(client, "alice")
    page = client.get("/dashboard").get_data(as_text=True)
    assert "Bob Smith" in page
    assert "Admin User" in page  # users without a family are visible to everyone
    assert "Carol Jones" not in page
    assert "Smith Guest" not in page  # guests are never listed


def test_user_without_family_sees_everyone(client):
    login(client, "admin")
    page = client.get("/dashboard").get_data(as_text=True)
    for name in ("Alice Smith", "Bob Smith", "Carol Jones"):
        assert name in page


def test_user_gift_ideas_of_other_family_is_reachable(client, env):
    """CURRENT BEHAVIOR (likely a visibility hole, kept as a passing test on the
    owner's request until a fix is decided): /user_gift_ideas/<user> does
    not check families. alice (Smith) can open carol's (Jones) list directly by
    URL, including who bought what, although carol is hidden from her dashboard."""
    env.update_idea(4, bought_by="admin")

    login(client, "alice")
    client.get("/set_language/en")
    response = client.get("/user_gift_ideas/carol")
    assert response.status_code == 200
    page = response.get_data(as_text=True)
    assert "Carol own idea" in page
    assert "Purchased by: Admin User" in page


def test_table_view_ignores_families(client):
    """CURRENT BEHAVIOR (likely a visibility hole): /table_view lists every
    non-guest user, including other families."""
    login(client, "alice")
    response = client.get("/table_view")
    assert response.status_code == 200
    assert "Carol Jones" in response.get_data(as_text=True)


# 8. Guests -----------------------------------------------------------------------

def test_guest_login_and_allowed_route(client):
    response = client.post("/guest_login", data={"password": "guestpass"})
    assert is_redirect_to(response, "/dashboard")
    assert session_username(client) == "guest_smith"

    page = client.get("/dashboard")
    assert page.status_code == 200
    text = page.get_data(as_text=True)
    assert "Alice Smith" in text and "Bob Smith" in text
    assert "Carol Jones" not in text
    assert "Admin User" not in text  # family guests only see members of their families

    assert client.get("/user_gift_ideas/bob").status_code == 200


def test_guest_can_open_other_family_list_by_url(client, env):
    """CURRENT BEHAVIOR (likely a visibility hole): same missing family check
    as for regular users, so the Smith family guest can read the Jones
    family's list, buyers included, by URL."""
    env.update_idea(4, bought_by="admin")
    client.post("/guest_login", data={"password": "guestpass"})
    client.get("/set_language/en")
    response = client.get("/user_gift_ideas/carol")
    assert response.status_code == 200
    page = response.get_data(as_text=True)
    assert "Carol own idea" in page
    assert "Purchased by: Admin User" in page


def test_guest_login_with_wrong_password(client):
    response = client.post("/guest_login", data={"password": "nope"})
    assert is_redirect_to(response, "/login")
    assert session_username(client) is None


@pytest.mark.parametrize("method,path", [("get", "/my_ideas"), ("post", "/change_password"), ("get", "/add_idea/bob")])
def test_guest_is_refused_on_non_guest_routes(client, method, path):
    client.post("/guest_login", data={"password": "guestpass"})
    client.get("/dashboard")  # consume the login flash message
    response = getattr(client, method)(path)
    assert is_redirect_to(response, "/dashboard")
    assert [category for category, _ in flashes(client)] == ["danger"]


# 9. Public share links -----------------------------------------------------------

def test_manage_sharing_creates_a_link(client, env, make_client):
    login(client, "bob")
    response = client.post("/manage_sharing", data={"create_link": "1", "link_name": "Bob list", "days_valid": "10",
                                                    "allow_purchases": "true"})
    assert response.status_code == 200
    links = env.user("bob")["sharing"]["public_links"]
    assert len(links) == 1
    token = links[0]["token"]
    assert links[0]["is_active"] is True
    assert links[0]["allow_purchases"] is True
    created = datetime.strptime(links[0]["created_at"], "%Y-%m-%d %H:%M:%S")
    expires = datetime.strptime(links[0]["expires_at"], "%Y-%m-%d %H:%M:%S")
    # two separate datetime.now() calls, truncated to the second
    assert abs(expires - created - timedelta(days=10)) <= timedelta(seconds=1)

    anonymous = make_client()
    page = anonymous.get(f"/shared/{token}")
    assert page.status_code == 200
    assert "Bob own idea" in page.get_data(as_text=True)


def test_shared_link_renders(client):
    response = client.get(f"/shared/{SHARE_TOKEN}")
    assert response.status_code == 200
    assert "Alice own idea" in response.get_data(as_text=True)


def test_owner_can_open_own_share_link_and_see_buyers(client, env):
    """CURRENT BEHAVIOR (likely breaks the surprise rule): /shared/<token> is
    public, so the list owner can open her own link, and the page prints
    'Purchased by <full name>' for every bought idea."""
    login(client, "alice")
    client.get("/set_language/en")
    page = client.get(f"/shared/{SHARE_TOKEN}").get_data(as_text=True)
    assert "Secret telescope" in page
    assert "Purchased by: Bob Smith" in page


def test_shared_link_unknown_token(client):
    assert client.get("/shared/does-not-exist").status_code == 404


def test_shared_link_expired_token(client):
    assert client.get(f"/shared/{EXPIRED_TOKEN}").status_code == 410


def test_shared_link_inactive_token(client, env):
    env.update_share_link("alice", SHARE_TOKEN, is_active=False)
    assert client.get(f"/shared/{SHARE_TOKEN}").status_code == 410


def test_shared_link_refused_when_link_sharing_disabled(client, env):
    env.set_env("ENABLE_LINK_SHARING", "false")
    assert client.get(f"/shared/{SHARE_TOKEN}").status_code == 404


def test_manage_sharing_refused_when_link_sharing_disabled(client, env):
    env.set_env("ENABLE_LINK_SHARING", "false")
    login(client, "alice")
    assert is_redirect_to(client.get("/manage_sharing"), "/dashboard")


def test_shared_link_mark_bought_and_not_bought(client, env):
    response = client.post(f"/shared/{SHARE_TOKEN}/mark_bought/1", json={"visitor_name": "Uncle Joe"})
    assert response.status_code == 200
    body = response.get_json()
    assert body["success"] is True
    idea = env.idea(1)
    assert idea["bought_by"] == "visitor:Uncle Joe"
    assert idea["visitor_id"] == body["visitor_id"]
    purchases = env.user("alice")["sharing"]["public_links"][0]["visitor_purchases"]
    assert [p["idea_id"] for p in purchases] == [1]

    response = client.post(f"/shared/{SHARE_TOKEN}/mark_not_bought/1", json={"visitor_id": body["visitor_id"]})
    assert response.status_code == 200
    assert not env.idea(1)["bought_by"]
    assert env.user("alice")["sharing"]["public_links"][0]["visitor_purchases"] == []


def test_shared_link_mark_bought_refused_when_purchases_not_allowed(client, env):
    env.update_share_link("alice", SHARE_TOKEN, allow_purchases=False)
    response = client.post(f"/shared/{SHARE_TOKEN}/mark_bought/1", json={"visitor_name": "Uncle Joe"})
    assert response.status_code == 403
    assert env.idea(1)["bought_by"] is None


def test_shared_link_mark_bought_on_other_users_idea_is_refused(client, env):
    response = client.post(f"/shared/{SHARE_TOKEN}/mark_bought/3", json={"visitor_name": "Uncle Joe"})
    assert response.status_code == 404
    assert env.idea(3)["bought_by"] is None


def test_shared_link_mark_bought_with_expired_token_is_refused(client, env):
    response = client.post(f"/shared/{EXPIRED_TOKEN}/mark_bought/1", json={"visitor_name": "Uncle Joe"})
    assert response.status_code == 404
    assert env.idea(1)["bought_by"] is None


@pytest.mark.xfail(
    reason="Bug: /shared/<token>/mark_not_bought crashes (AttributeError on None.startswith, HTTP 500) "
           "when the idea is not bought, because bought_by is stored as null rather than missing",
    raises=AttributeError,
    strict=True,
)
def test_shared_link_cancel_purchase_of_unbought_idea_is_refused(client, env):
    response = client.post(f"/shared/{SHARE_TOKEN}/mark_not_bought/1", json={"visitor_id": "someone"})
    assert response.status_code == 403


@pytest.mark.xfail(
    reason="Bug: /shared/<token>/mark_bought is not gated by ENABLE_LINK_SHARING, "
           "visitors can still mark items bought when link sharing is disabled",
    raises=AssertionError,
    strict=True,
)
def test_shared_link_mark_bought_refused_when_link_sharing_disabled(client, env):
    env.set_env("ENABLE_LINK_SHARING", "false")
    response = client.post(f"/shared/{SHARE_TOKEN}/mark_bought/1", json={"visitor_name": "Uncle Joe"})
    assert response.status_code != 200
    assert env.idea(1)["bought_by"] is None


@pytest.mark.xfail(
    reason="Bug: /shared/<token>/mark_not_bought is not gated by ENABLE_LINK_SHARING, "
           "visitors can still cancel purchases when link sharing is disabled",
    raises=AssertionError,
    strict=True,
)
def test_shared_link_mark_not_bought_refused_when_link_sharing_disabled(client, env):
    visitor_id = client.post(f"/shared/{SHARE_TOKEN}/mark_bought/1",
                             json={"visitor_name": "Uncle Joe"}).get_json()["visitor_id"]
    env.set_env("ENABLE_LINK_SHARING", "false")
    response = client.post(f"/shared/{SHARE_TOKEN}/mark_not_bought/1", json={"visitor_id": visitor_id})
    assert response.status_code != 200
    assert env.idea(1)["bought_by"] == "visitor:Uncle Joe"


# 10. og:image preview ----------------------------------------------------------

def _fake_response(html):
    response = mock.Mock()
    response.text = html
    response.raise_for_status.return_value = None
    return response


def test_fetch_og_image_returns_absolute_image_url(client, app_module):
    login(client, "alice")
    html = '<html><head><meta property="og:image" content="/img/cover.jpg"></head></html>'
    with mock.patch.object(app_module.requests, "get", return_value=_fake_response(html)) as fake_get:
        response = client.get("/fetch_og_image", query_string={"url": "https://shop.example/item/42"})
    assert response.status_code == 200
    assert response.get_json() == {"og_image_url": "https://shop.example/img/cover.jpg"}
    fake_get.assert_called_once()
    assert fake_get.call_args.args[0] == "https://shop.example/item/42"


def test_fetch_og_image_falls_back_to_image_src(client, app_module):
    login(client, "alice")
    html = '<html><head><link rel="image_src" href="/a.jpg"></head></html>'
    with mock.patch.object(app_module.requests, "get", return_value=_fake_response(html)):
        response = client.get("/fetch_og_image", query_string={"url": "https://shop.example/item/42"})
    assert response.get_json() == {"og_image_url": "https://shop.example/a.jpg"}


def test_fetch_og_image_without_image(client, app_module):
    login(client, "alice")
    with mock.patch.object(app_module.requests, "get", return_value=_fake_response("<html></html>")):
        response = client.get("/fetch_og_image", query_string={"url": "https://shop.example/"})
    assert response.status_code == 404


def test_fetch_og_image_requires_url(client):
    login(client, "alice")
    assert client.get("/fetch_og_image").status_code == 400


def test_fetch_og_image_does_not_require_login(client, app_module):
    """CURRENT BEHAVIOR (likely a security hole): /fetch_og_image has no
    @login_required, so an anonymous visitor can make the server fetch any URL
    (with TLS verification disabled), e.g. internal addresses (SSRF)."""
    html = '<meta property="og:image" content="https://internal.example/x.png">'
    with mock.patch.object(app_module.requests, "get", return_value=_fake_response(html)) as fake_get:
        response = client.get("/fetch_og_image", query_string={"url": "http://10.0.0.1/"})
    assert response.status_code == 200
    assert fake_get.call_args.args[0] == "http://10.0.0.1/"
    assert fake_get.call_args.kwargs.get("verify") is False


# 11. Secret Santa --------------------------------------------------------------

def test_secret_santa_draw_is_a_derangement(client, env):
    participants = ["alice", "bob", "carol"]
    login(client, "admin")
    for _ in range(20):  # the draw is random: repeat it so an occasional self-draw would show up
        response = client.post(
            "/secret_santa",
            data={"participants": participants, "pool_name": "Xmas", "instructions": "Max 20"},
        )
        assert is_redirect_to(response, "/secret_santa_assignments")

        assignments = {u["username"]: u["assigned_users"]["Xmas"] for u in env.users() if "assigned_users" in u}
        assert set(assignments) == set(participants)
        assert sorted(assignments.values()) == sorted(participants)  # a permutation
        assert all(giver != target for giver, target in assignments.items())  # nobody draws themselves
    assert (env.data_dir / "santa_inst_Xmas.txt").read_text() == "Max 20"


def test_secret_santa_assignment_visible_to_participant(client, env, make_client):
    login(client, "admin")
    client.post("/secret_santa", data={"participants": ["alice", "bob", "carol"], "pool_name": "Xmas"})
    target_username = env.user("alice")["assigned_users"]["Xmas"]
    target = env.user(target_username)["full_name"]
    other = env.user(({"bob", "carol"} - {target_username}).pop())["full_name"]

    participant = make_client()
    login(participant, "alice")
    response = participant.get("/secret_santa_assignments")
    assert response.status_code == 200
    page = response.get_data(as_text=True)
    assert target in page
    assert other not in page  # only alice's own draw is shown


# 12. Language ------------------------------------------------------------------

def test_set_language_stores_locale_in_session(client):
    response = client.get("/set_language/en")
    assert response.status_code == 302
    with client.session_transaction() as sess:
        assert sess["lang"] == "en"


def test_set_language_ignores_unsupported_code(client):
    client.get("/set_language/xx")
    with client.session_transaction() as sess:
        assert "lang" not in sess
