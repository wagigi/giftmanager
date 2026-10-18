"""Smoke tests of the main routes, including access control and the surprise rule.

They freeze the current behavior. When a test documents questionable
behavior, the docstring says so (see the Tests section of CLAUDE.md).
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


@pytest.mark.parametrize("path", ["/dashboard", "/my_ideas", "/user_gift_ideas/bob", "/admin"])
def test_session_of_deleted_user_is_logged_out(client, env, path):
    login(client, "alice")
    env.write_users([u for u in env.users() if u["username"] != "alice"])
    assert is_redirect_to(client.get(path), "/login")
    assert session_username(client) is None
    assert [category for category, _ in flashes(client)] == ["login_warning"]  # shown on the login page


def test_session_of_deleted_guest_is_logged_out(client, env):
    client.post("/guest_login", data={"password": "guestpass"})
    env.write_users([u for u in env.users() if u["username"] != "guest_smith"])
    assert is_redirect_to(client.get("/dashboard"), "/login")
    assert session_username(client) is None


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


@pytest.mark.parametrize("path", ["/add_idea/bob", "/add2/"])
def test_add_idea_recipients_are_the_visible_users(client, env, path):
    """The recipient dropdown offers the dashboard's users: never another
    family, never a guest (even one without a family)."""
    env.update_user("guest_smith", access_type="people", groups=[], access_users=["bob"])
    login(client, "alice")
    page = client.get(path).get_data(as_text=True)
    for name in ("Alice Smith", "Bob Smith", "Admin User", "Smith Shared List"):
        assert name in page
    assert "Carol Jones" not in page
    assert "Smith Guest" not in page


def test_add_idea_for_user_of_other_family_is_refused(client, env):
    login(client, "alice")
    for path in ("/add_idea/carol", "/add2/"):
        response = client.post(path, data={"user": "carol", "name": "Sneaky", "description": "", "link": "",
                                           "value": "", "imagePath": ""})
        assert is_redirect_to(response, "/dashboard")
    assert "Sneaky" not in [i["gift_name"] for i in env.ideas()]


def test_add_idea_for_self_and_shared_list(client, env):
    login(client, "alice")
    for target in ("alice", "shared_smith"):
        client.post("/add2/", data={"user": target, "name": f"For {target}", "imagePath": ""})
    assert {i["user_id"] for i in env.ideas() if i["gift_name"].startswith("For ")} == {"alice", "shared_smith"}


def test_update_order_only_changes_own_ideas(client, env):
    login(client, "alice")
    response = client.post("/update_order", json={"order": [
        {"gift_idea_id": 1, "priority": 2},
        {"gift_idea_id": 4, "priority": 1},  # carol's idea
        {"gift_idea_id": 2, "priority": 3},  # on alice's list but added by bob (hidden from her)
    ]})
    assert response.status_code == 200
    assert env.idea(1)["priority"] == 2
    assert "priority" not in env.idea(4)
    assert "priority" not in env.idea(2)


# 5. Mark as bought / not bought --------------------------------------------------

def test_mark_as_bought_then_not_bought(client, env):
    """/mark_as_bought redirects to the recipient's list (it used to redirect to
    the buyer's own list). The UI calls it with fetch(), so the redirect is unused."""
    login(client, "alice")

    response = client.post("/mark_as_bought/3")
    assert is_redirect_to(response, "/user_gift_ideas/bob")
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


def test_already_bought_message_names_the_buyer_for_other_users(client, env):
    """Non-recipients may see the buyer: full name, or the visitor's name without the internal prefix."""
    login(client, "alice")
    client.get("/set_language/en")
    client.get("/dashboard")  # consume the login flash message
    client.post("/mark_as_bought/3")
    client.get("/dashboard")
    env.update_idea(3, bought_by="visitor:Uncle Joe")
    client.post("/mark_as_bought/3")
    assert [message for _, message in flashes(client)] == ['"Bob own idea" has already been bought by Uncle Joe.']
    env.update_idea(3, bought_by="admin")
    client.get("/dashboard")
    client.post("/mark_as_bought/3")
    assert [message for _, message in flashes(client)] == ['"Bob own idea" has already been bought by Admin User.']


def test_mark_as_not_bought_does_not_name_hidden_ideas(client, env):
    """The 'You did not buy "<name>"' refusal used to name any idea by id:
    ideas on invisible lists and surprise ideas on one's own list are now not found."""
    login(client, "alice")
    client.get("/dashboard")  # consume the login flash message
    for idea_id in (4, 2):  # carol's idea (other family), surprise idea for alice
        client.post(f"/mark_as_not_bought/{idea_id}")
        messages = [message for _, message in flashes(client)]
        assert len(messages) == 1
        assert "Carol own idea" not in messages[0] and "Secret telescope" not in messages[0]
        client.get("/dashboard")
    assert env.idea(2)["bought_by"] == "bob"


def test_already_bought_message_falls_back_to_buyer_username(client, env):
    """OIDC auto-registered accounts can have full_name null (used to read "bought by None")."""
    env.update_user("admin", full_name=None)
    env.update_idea(3, bought_by="admin")
    login(client, "alice")
    client.get("/set_language/en")
    client.get("/dashboard")  # consume the login flash message
    client.post("/mark_as_bought/3")
    assert [message for _, message in flashes(client)] == ['"Bob own idea" has already been bought by admin.']
    env.update_user("bob", full_name=None)
    env.update_idea(3, bought_by="alice")
    page = client.get("/bought_items").get_data(as_text=True)  # recipient: get_full_name("bob")
    assert "Bob own idea" in page and "None" not in page


def test_buyer_can_cancel_after_leaving_the_family(client, env):
    login(client, "alice")
    client.post("/mark_as_bought/3")
    env.update_user("bob", groups=["Jones"])
    client.post("/mark_as_not_bought/3")
    assert not env.idea(3)["bought_by"]


def test_only_the_buyer_can_mark_as_not_bought(client, env, make_client):
    login(client, "alice")
    client.post("/mark_as_bought/3")
    other = make_client()
    login(other, "admin")  # sees everyone, so only the buyer rule can refuse
    other.post("/mark_as_not_bought/3")  # always answers 204, refused or not
    assert env.idea(3)["bought_by"] == "alice"
    assert [category for category, _ in flashes(other)] == ["login_success", "danger"]


def test_mark_as_bought_respects_families(client, env):
    """alice (Smith) cannot buy carol's (Jones) idea by id: carol is not on her
    dashboard. The idea is reported as not found."""
    login(client, "alice")
    client.get("/dashboard")  # consume the login flash message
    response = client.post("/mark_as_bought/4")
    assert is_redirect_to(response, "/dashboard")
    assert env.idea(4)["bought_by"] is None
    assert [category for category, _ in flashes(client)] == ["danger"]


def test_guest_mark_as_bought_respects_families(client, env):
    client.post("/guest_login", data={"password": "guestpass"})
    client.post("/mark_as_bought/4")
    assert env.idea(4)["bought_by"] is None
    client.post("/mark_as_bought/3")  # bob is in the guest's family
    assert env.idea(3)["bought_by"] == "guest_smith"


def test_people_guest_only_sees_assigned_users(client, env):
    """A guest with access_type 'people' sees only its access_users."""
    env.update_user("guest_smith", access_type="people", groups=[], access_users=["carol"])
    client.post("/guest_login", data={"password": "guestpass"})
    assert client.get("/user_gift_ideas/carol").status_code == 200
    assert is_redirect_to(client.get("/user_gift_ideas/bob"), "/dashboard")
    client.post("/mark_as_bought/3")
    assert env.idea(3)["bought_by"] is None


# Deleting an idea --------------------------------------------------------------

def test_delete_own_idea(client, env):
    login(client, "alice")
    assert client.delete("/delete_idea/5").status_code == 204
    assert 5 not in [i["gift_idea_id"] for i in env.ideas()]


def test_delete_bought_idea_without_mailjet_keys(client, env, mailer_module):
    """The buyer email is skipped because the Mailjet keys are empty (no network call)."""
    login(client, "bob")
    with mock.patch.object(mailer_module, "Client") as mailjet_client:
        assert client.delete("/delete_idea/2").status_code == 204
    mailjet_client.assert_not_called()
    assert 2 not in [i["gift_idea_id"] for i in env.ideas()]


def test_delete_idea_of_someone_else_is_refused(client, env):
    """Answered as for an unknown id, so ideas on lists one cannot see are not revealed."""
    login(client, "carol")
    assert client.delete("/delete_idea/1").status_code == 404
    assert 1 in [i["gift_idea_id"] for i in env.ideas()]


def test_edit_idea_of_someone_else_is_refused(client, env):
    login(client, "bob")  # can see alice's list, but did not add idea 1
    client.get("/dashboard")  # consume the login flash message
    response = client.post("/edit_idea/1", data={"description": "changed"})
    assert is_redirect_to(response, "/dashboard")
    assert env.idea(1)["description"] != "changed"
    assert flashes(client) == [("danger", "Idée non trouvée")]


def test_delete_unknown_idea(client, env):
    """Used to crash with a 500 (idea['user_id'] read before the existence check)."""
    login(client, "alice")
    assert client.delete("/delete_idea/999").status_code == 404
    assert len(env.ideas()) == 5


def test_recipient_cannot_delete_idea_others_added(client, env):
    """Ideas others added for the recipient are hidden from them: same answer as an unknown id."""
    login(client, "alice")
    client.get("/dashboard")  # consume the login flash message
    assert client.delete("/delete_idea/2").status_code == 404
    assert 2 in [i["gift_idea_id"] for i in env.ideas()]
    assert flashes(client) == []  # called with fetch(): nothing left for a later page


def test_recipient_cannot_edit_idea_others_added(client, env):
    login(client, "alice")
    client.get("/dashboard")  # consume the login flash message
    assert is_redirect_to(client.get("/edit_idea/2"), "/dashboard")
    response = client.post("/edit_idea/2", data={"description": "changed"})
    assert is_redirect_to(response, "/dashboard")
    assert env.idea(2)["description"] != "changed"
    assert [category for category, _ in flashes(client)] == ["danger", "danger"]


def test_adder_can_edit_idea_for_someone_else(client, env):
    login(client, "bob")
    response = client.post("/edit_idea/2", data={"description": "changed"})
    assert is_redirect_to(response, "/user_gift_ideas/alice")
    assert env.idea(2)["description"] == "changed"


def test_edit_unknown_idea(client):
    """Same missing existence check as /delete_idea (used to crash with a 500)."""
    login(client, "alice")
    client.get("/dashboard")  # consume the login flash message
    assert is_redirect_to(client.get("/edit_idea/999"), "/dashboard")
    assert [category for category, _ in flashes(client)] == ["danger"]


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


def test_recipient_mark_as_bought_does_not_reveal_buyer(client, env):
    login(client, "alice")
    client.get("/dashboard")  # consume the login flash message
    response = client.post("/mark_as_bought/2")
    assert env.idea(2)["bought_by"] == "bob"
    bought_answer = (response.headers["Location"], flashes(client))
    assert not any("bob" in message.lower() for _, message in bought_answer[1])

    # Same answer for an idea of hers that is not bought: nothing tells them apart
    client.get("/dashboard")  # consume the flash message
    response = client.post("/mark_as_bought/1")
    assert env.idea(1)["bought_by"] is None
    assert (response.headers["Location"], flashes(client)) == bought_answer


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


def test_recipient_table_view_hides_surprises(client, make_client):
    """Like /my_ideas, alice's own column only lists the ideas she added
    herself: the surprise idea added (and bought) by bob is not shown, nor any
    bought marker. Idea 2 is the only bought idea in the fixtures."""
    login(client, "alice")
    page = client.get("/table_view").get_data(as_text=True)
    assert "Alice own idea" in page
    assert "Secret telescope" not in page
    assert "fa-check-circle" not in page
    assert "Bob Smith" in page  # bob's column header, not a buyer marker

    other = make_client()
    login(other, "admin")  # no family: sees alice's column with the bought marker
    page = other.get("/table_view").get_data(as_text=True)
    assert "Secret telescope" in page
    assert page.count("fa-check-circle") == 1


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


def test_user_gift_ideas_of_other_family_is_refused(client, env):
    """alice (Smith) cannot open carol's (Jones) list by URL: carol is hidden
    from her dashboard, so the list is refused like other denied pages."""
    env.update_idea(4, bought_by="admin")

    login(client, "alice")
    client.get("/dashboard")  # consume the login flash message
    response = client.get("/user_gift_ideas/carol")
    assert is_redirect_to(response, "/dashboard")
    assert [category for category, _ in flashes(client)] == ["danger"]


@pytest.mark.parametrize("target", ["bob", "admin", "shared_smith"])
def test_user_gift_ideas_of_visible_user_is_reachable(client, env, target):
    """Same family, users without a family and shared lists stay reachable."""
    env.write_ideas(env.ideas() + [dict(env.idea(3), gift_idea_id=10 + len(target), user_id=target)])
    login(client, "alice")
    assert client.get(f"/user_gift_ideas/{target}").status_code == 200


def test_shared_list_members_keep_access_when_list_is_in_another_family(client, env, make_client):
    env.update_user("shared_smith", groups=["Jones"])
    env.write_ideas(env.ideas() + [dict(env.idea(3), gift_idea_id=20, user_id="shared_smith", gift_name="Shared idea")])
    login(client, "alice")  # member, family Smith
    assert client.get("/user_gift_ideas/shared_smith").status_code == 200

    guest = make_client()  # Smith family guest, not a member
    guest.post("/guest_login", data={"password": "guestpass"})
    assert is_redirect_to(guest.get("/user_gift_ideas/shared_smith"), "/dashboard")


def test_table_view_lists_shared_lists_of_another_family_for_members(client, env):
    env.update_user("shared_smith", groups=["Jones"])
    login(client, "alice")
    assert "Smith Shared List" in client.get("/table_view").get_data(as_text=True)


def test_user_gift_ideas_of_unknown_user_is_refused(client):
    login(client, "alice")
    assert is_redirect_to(client.get("/user_gift_ideas/nobody"), "/dashboard")


def test_table_view_respects_families(client):
    """/table_view shows the same users as the dashboard."""
    login(client, "alice")
    response = client.get("/table_view")
    assert response.status_code == 200
    page = response.get_data(as_text=True)
    assert "Bob Smith" in page and "Admin User" in page
    assert "Carol Jones" not in page and "Carol own idea" not in page
    assert "Smith Guest" not in page


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


def test_guest_cannot_open_other_family_list_by_url(client, env):
    """The Smith family guest cannot read the Jones family's list by URL, nor
    the list of a user without a family (family guests only see their families)."""
    env.update_idea(4, bought_by="admin")
    client.post("/guest_login", data={"password": "guestpass"})
    assert is_redirect_to(client.get("/user_gift_ideas/carol"), "/dashboard")
    assert is_redirect_to(client.get("/user_gift_ideas/admin"), "/dashboard")


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


def test_owner_opening_own_share_link_sees_no_surprise(client, env):
    """When the logged-in owner opens her own link, the page is shown like
    /my_ideas: only her own ideas, nothing marked bought, no purchase buttons."""
    env.update_idea(1, bought_by="visitor:Uncle Joe", visitor_id="v1")
    login(client, "alice")
    client.get("/set_language/en")
    page = client.get(f"/shared/{SHARE_TOKEN}").get_data(as_text=True)
    assert "Alice own idea" in page and "Alice second idea" in page
    assert "Secret telescope" not in page  # added by bob
    assert "Purchased by" not in page and "Uncle Joe" not in page and "Bob Smith" not in page
    assert "I Purchased This" not in page and "Cancel Purchase" not in page

    response = client.post(f"/shared/{SHARE_TOKEN}/mark_bought/5", json={"visitor_name": "Alice"})
    assert response.status_code == 403
    assert env.idea(5)["bought_by"] is None


def test_owner_cannot_probe_hidden_ideas_through_own_share_link(client, env):
    """Cancelling a purchase on an idea others added answered 403, unlike an unknown idea (404)."""
    login(client, "alice")
    response = client.post(f"/shared/{SHARE_TOKEN}/mark_not_bought/2", json={"visitor_id": "x"})
    assert response.status_code == 404
    assert env.idea(2)["bought_by"] == "bob"


def test_share_link_still_shows_purchases_to_visitors(client):
    login(client, "bob")  # logged in, but not the owner
    client.get("/set_language/en")
    page = client.get(f"/shared/{SHARE_TOKEN}").get_data(as_text=True)
    assert "Secret telescope" in page
    assert "Purchased by: Bob Smith" in page
    assert "I Purchased This" in page


def test_shared_link_unknown_token(client):
    assert client.get("/shared/does-not-exist").status_code == 404


def test_shared_link_expired_token(client):
    assert client.get(f"/shared/{EXPIRED_TOKEN}").status_code == 410


@pytest.mark.parametrize("expires_at", [None, "2026-12-01 10:00", "soon"])
def test_shared_link_with_unreadable_expiry_is_refused(client, env, expires_at):
    """Used to crash with a 500 (strptime on a missing or malformed date)."""
    env.update_share_link("alice", SHARE_TOKEN, expires_at=expires_at)
    assert client.get(f"/shared/{SHARE_TOKEN}").status_code == 410
    response = client.post(f"/shared/{SHARE_TOKEN}/mark_bought/1", json={"visitor_name": "Zoe"})
    assert response.status_code == 404 and env.idea(1)["bought_by"] is None  # as for an expired link


def test_update_order_tolerates_ideas_without_adder(client, env):
    """Legacy ideas without added_by used to make /update_order fail with a 500."""
    ideas = env.ideas()
    del next(i for i in ideas if i["gift_idea_id"] == 5)["added_by"]
    env.write_ideas(ideas)
    login(client, "alice")
    response = client.post("/update_order", json={"order": [{"gift_idea_id": 5, "priority": 1}]})
    assert response.status_code == 200
    assert "priority" not in env.idea(5)


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


def test_shared_link_mark_bought_with_inactive_token_is_refused(client, env):
    env.update_share_link("alice", SHARE_TOKEN, is_active=False)
    response = client.post(f"/shared/{SHARE_TOKEN}/mark_bought/1", json={"visitor_name": "Uncle Joe"})
    assert response.status_code == 404
    assert env.idea(1)["bought_by"] is None


def test_shared_link_mark_not_bought_with_expired_token_is_refused(client, env):
    visitor_id = client.post(f"/shared/{SHARE_TOKEN}/mark_bought/1",
                             json={"visitor_name": "Uncle Joe"}).get_json()["visitor_id"]
    env.update_share_link("alice", SHARE_TOKEN, expires_at="2000-01-01 00:00:00")
    response = client.post(f"/shared/{SHARE_TOKEN}/mark_not_bought/1", json={"visitor_id": visitor_id})
    assert response.status_code == 404
    assert env.idea(1)["bought_by"] == "visitor:Uncle Joe"


def test_shared_link_mark_bought_without_json_body_is_refused(client, env):
    response = client.post(f"/shared/{SHARE_TOKEN}/mark_bought/1")
    assert response.status_code == 400
    assert env.idea(1)["bought_by"] is None


def test_shared_link_mark_bought_with_expired_token_is_refused(client, env):
    response = client.post(f"/shared/{EXPIRED_TOKEN}/mark_bought/1", json={"visitor_name": "Uncle Joe"})
    assert response.status_code == 404
    assert env.idea(1)["bought_by"] is None


def test_shared_link_cancel_purchase_of_unbought_idea_is_refused(client, env):
    """bought_by is stored as null on ideas that are not bought (used to crash with a 500)."""
    response = client.post(f"/shared/{SHARE_TOKEN}/mark_not_bought/1", json={"visitor_id": "someone"})
    assert response.status_code == 403
    assert env.idea(1)["bought_by"] is None


def test_shared_link_mark_bought_refused_when_link_sharing_disabled(client, env):
    env.set_env("ENABLE_LINK_SHARING", "false")
    response = client.post(f"/shared/{SHARE_TOKEN}/mark_bought/1", json={"visitor_name": "Uncle Joe"})
    assert response.status_code == 404
    assert env.idea(1)["bought_by"] is None


def test_shared_link_mark_not_bought_refused_when_link_sharing_disabled(client, env):
    visitor_id = client.post(f"/shared/{SHARE_TOKEN}/mark_bought/1",
                             json={"visitor_name": "Uncle Joe"}).get_json()["visitor_id"]
    env.set_env("ENABLE_LINK_SHARING", "false")
    response = client.post(f"/shared/{SHARE_TOKEN}/mark_not_bought/1", json={"visitor_id": visitor_id})
    assert response.status_code == 404
    assert env.idea(1)["bought_by"] == "visitor:Uncle Joe"


# 10. og:image preview ----------------------------------------------------------

def _fake_response(html):
    response = mock.Mock()
    response.text = html
    response.raise_for_status.return_value = None
    return response


def test_fetch_og_image_returns_absolute_image_url(client, og_image_module):
    login(client, "alice")
    html = '<html><head><meta property="og:image" content="/img/cover.jpg"></head></html>'
    with mock.patch.object(og_image_module.requests, "get", return_value=_fake_response(html)) as fake_get:
        response = client.get("/fetch_og_image", query_string={"url": "https://shop.example/item/42"})
    assert response.status_code == 200
    assert response.get_json() == {"og_image_url": "https://shop.example/img/cover.jpg"}
    fake_get.assert_called_once()
    assert fake_get.call_args.args[0] == "https://shop.example/item/42"
    assert fake_get.call_args.kwargs["timeout"] == 10  # a host that never answers must not hold a thread


def test_fetch_og_image_falls_back_to_image_src(client, og_image_module):
    login(client, "alice")
    html = '<html><head><link rel="image_src" href="/a.jpg"></head></html>'
    with mock.patch.object(og_image_module.requests, "get", return_value=_fake_response(html)):
        response = client.get("/fetch_og_image", query_string={"url": "https://shop.example/item/42"})
    assert response.get_json() == {"og_image_url": "https://shop.example/a.jpg"}


def test_fetch_og_image_without_image(client, og_image_module):
    login(client, "alice")
    with mock.patch.object(og_image_module.requests, "get", return_value=_fake_response("<html></html>")):
        response = client.get("/fetch_og_image", query_string={"url": "https://shop.example/"})
    assert response.status_code == 404


def test_fetch_og_image_requires_url(client):
    login(client, "alice")
    assert client.get("/fetch_og_image").status_code == 400


def test_fetch_og_image_requires_login(client, og_image_module):
    """Anonymous visitors could make the server fetch any URL (SSRF). TLS
    verification is still disabled for logged-in users (known issue)."""
    with mock.patch.object(og_image_module.requests, "get") as fake_get:
        response = client.get("/fetch_og_image", query_string={"url": "http://10.0.0.1/"})
    assert is_redirect_to(response, "/login")
    fake_get.assert_not_called()


def test_fetch_og_image_refused_to_guests(client, og_image_module):
    client.post("/guest_login", data={"password": "guestpass"})
    with mock.patch.object(og_image_module.requests, "get") as fake_get:
        response = client.get("/fetch_og_image", query_string={"url": "http://10.0.0.1/"})
    assert is_redirect_to(response, "/dashboard")
    fake_get.assert_not_called()


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


# First-start setup -------------------------------------------------------------

def test_setup_wizard_saves_environment(client, env):
    env.write_users([])
    response = client.post("/setupadmin", data={"admin_username": "root", "admin_password": "pw",
                                                "admin_email": "root@example.com", "full_name": "Root",
                                                "birthday": "", "avatar": "icons/avatar1.png"})
    assert is_redirect_to(response, "/setupenv")
    assert client.get("/setupenv").status_code == 200
    response = client.post("/setupenv", data={"DELETE_DAYS": "45", "SYSTEM_EMAIL": "noreply@example.com"})
    assert is_redirect_to(response, "/")
    assert "DELETE_DAYS='45'" in env.env_file.read_text()

    assert [category for category, _ in flashes(client)][-1] == "success"  # no OIDC set: no restart notice

    # One-shot: the wizard cannot be replayed
    assert is_redirect_to(client.post("/setupenv", data={"DELETE_DAYS": "1"}), "/login")
    assert "DELETE_DAYS='45'" in env.env_file.read_text()


def test_setup_wizard_closes_when_leaving_for_login(client, env):
    env.write_users([])
    client.post("/setupadmin", data={"admin_username": "root", "admin_password": "pw",
                                     "admin_email": "root@example.com", "full_name": "Root",
                                     "birthday": "", "avatar": "icons/avatar1.png"})
    client.get("/login")
    assert is_redirect_to(client.post("/setupenv", data={"DELETE_DAYS": "1"}), "/login")
    assert "DELETE_DAYS='1'" not in env.env_file.read_text()


@pytest.mark.parametrize("days", ["", "0", "abc", "1000000", "²"])
def test_setup_wizard_saves_default_for_invalid_delete_days(client, env, days):
    env.write_users([])
    client.post("/setupadmin", data={"admin_username": "root", "admin_password": "pw",
                                     "admin_email": "root@example.com", "full_name": "Root",
                                     "birthday": "", "avatar": "icons/avatar1.png"})
    client.post("/setupenv", data={"DELETE_DAYS": days})
    assert "DELETE_DAYS='30'" in env.env_file.read_text()


def test_setupenv_refuses_spoofed_referer(client, env):
    """/setupenv is unauthenticated; it used to trust any Referer containing '/setupadmin'."""
    before = env.env_file.read_text()
    response = client.post("/setupenv", data={"ENABLE_AUTO_REGISTRATION": "true", "PRIMARY_DB_FIELD": "full_name"},
                           headers={"Referer": "http://evil.example/setupadmin"})
    assert is_redirect_to(response, "/login")
    assert env.env_file.read_text() == before


def test_setup_wizard_warns_that_oidc_needs_a_restart(client, env):
    env.write_users([])
    client.post("/setupadmin", data={"admin_username": "root", "admin_password": "pw", "admin_email": "",
                                     "full_name": "Root", "birthday": "", "avatar": "icons/avatar1.png"})
    client.post("/setupenv", data={"OIDC_CLIENT_ID": "client"})
    assert [category for category, _ in flashes(client)][-1] == "login_warning"
