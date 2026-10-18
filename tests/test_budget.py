"""Budgets per giver and recipient, cost sharing and the family overview (budgets.json)."""
from datetime import datetime, timedelta

import pytest

from smoke_helpers import PASSWORDS, flashes, is_redirect_to, login


def _user(username, groups=None, **extra):
    data = {"username": username, "full_name": username.title()}
    if groups is not None:
        data["groups"] = groups
    data.update(extra)
    return data


def _expense(paid_by, amount, individual=False, idea_id=None, id=1):
    return {"id": id, "paid_by": paid_by, "amount": amount, "label": "x", "idea_id": idea_id,
            "individual": individual, "date": "2026-10-01 10:00:00"}


def _entry(budgets, *expenses):
    return {"budgets": budgets, "expenses": list(expenses)}


def _sharing(env, budgets=None, expenses=()):
    """Budget entry for bob's list in the test data directory."""
    env.write_budgets({"recipients": {"bob": _entry(budgets or {}, *expenses)}, "settlements": []})


def _en(client, username):
    login(client, username)
    client.get("/set_language/en")


# --- recipient_split ---------------------------------------------------------------------------

def test_split_under_budget_is_proportional(budget_module):
    split = budget_module.recipient_split(_entry({"alice": 50, "carol": 30},
                                                 _expense("alice", 42), _expense("carol", 8, id=2)))
    assert split["total_spent"] == 5000 and split["total_budget"] == 8000
    assert split["shares"] == {"alice": 3125, "carol": 1875}
    assert split["balances"] == {"alice": 1075, "carol": -1075}
    assert split["uncovered"] == 0


def test_split_over_budget_caps_shares_and_reports_uncovered(budget_module):
    split = budget_module.recipient_split(_entry({"alice": 20, "bob": 10}, _expense("alice", 50)))
    assert split["shares"] == {"alice": 2000, "bob": 1000}
    assert split["uncovered"] == 2000
    # The uncovered 20 stays with alice, who paid it: bob still owes his whole budget
    assert split["balances"] == {"alice": 1000, "bob": -1000}


def test_split_payer_without_budget_is_fully_reimbursed(budget_module):
    split = budget_module.recipient_split(_entry({"alice": 30, "bob": 0}, _expense("carol", 10)))
    assert split["shares"] == {"alice": 1000}
    assert split["balances"] == {"alice": -1000, "carol": 1000}


def test_split_ignores_individual_gifts(budget_module):
    split = budget_module.recipient_split(_entry({"alice": 30, "carol": 30},
                                                 _expense("alice", 20), _expense("carol", 100, individual=True, id=2)))
    assert split["total_spent"] == 2000
    assert split["individual_spent"] == 10000
    assert split["balances"] == {"alice": 1000, "carol": -1000}


def test_split_rounds_to_the_cent_without_losing_any(budget_module):
    split = budget_module.recipient_split(_entry({"a": 10, "b": 10, "c": 10}, _expense("a", 10)))
    assert sorted(split["shares"].values()) == [333, 333, 334]
    assert sum(split["balances"].values()) == 0


def test_split_without_budgets_shares_nothing(budget_module):
    split = budget_module.recipient_split(_entry({}, _expense("alice", 10), _expense("bob", 0, id=2)))
    assert split["uncovered"] == 1000
    assert all(balance == 0 for balance in split["balances"].values())


def test_split_counts_a_missing_price_as_zero(budget_module):
    split = budget_module.recipient_split(_entry({"alice": 10}, _expense("bob", None)))
    assert split["total_spent"] == 0


@pytest.mark.parametrize("text, expected", [
    ("12,50", 12.5), (" 8 ", 8.0), ("1\u202f234,50", 1234.5), ("1\u00a0234", 1234.0), ("3.333", 3.33), ("", None), ("abc", None), ("-1", None), ("nan", None), ("inf", None),
])
def test_parse_amount(budget_module, text, expected):
    assert budget_module.parse_amount(text) == expected


# --- family settlement -------------------------------------------------------------------------

FAMILY = [_user("alice", ["Smith"]), _user("bob", ["Smith"]), _user("dave", ["Smith"]), _user("erin", ["Smith"]),
          _user("carol", ["Jones"]), _user("frank", ["Jones"])]


def test_family_debts_offset_each_other(budget_module):
    budgets = {"recipients": {
        # For dave: bob paid 40, alice's share is 20 -> alice owes bob 20
        "dave": _entry({"alice": 20, "bob": 20}, _expense("bob", 40)),
        # For erin: alice paid 30, bob's share is 15 -> bob owes alice 15
        "erin": _entry({"alice": 15, "bob": 15}, _expense("alice", 30)),
    }, "settlements": []}
    assert budget_module.scope_transfers(budgets, "Smith", FAMILY) == [("alice", "bob", 500)]


def test_family_settlements_reduce_the_debts(budget_module):
    budgets = {"recipients": {"dave": _entry({"alice": 20, "bob": 20}, _expense("bob", 40))}, "settlements": []}
    budget_module.add_settlement(budgets, "Smith", "alice", "bob", 12.5)
    assert budget_module.scope_transfers(budgets, "Smith", FAMILY) == [("alice", "bob", 750)]
    budget_module.add_settlement(budgets, "Smith", "alice", "bob", 7.5)
    assert budget_module.scope_transfers(budgets, "Smith", FAMILY) == []


def test_family_scopes_are_separate(budget_module):
    budgets = {"recipients": {
        "dave": _entry({"alice": 20, "bob": 20}, _expense("bob", 40)),
        "carol": _entry({"frank": 10, "alice": 10}, _expense("alice", 20)),
    }, "settlements": []}
    assert budget_module.scope_transfers(budgets, "Smith", FAMILY) == [("alice", "bob", 2000)]
    assert budget_module.scope_transfers(budgets, "Jones", FAMILY) == [("frank", "alice", 1000)]
    # alice is not in Jones, but she is owed money there, so she can open it
    assert budget_module.user_scopes(FAMILY[0], FAMILY, budgets) == ["Smith", "Jones"]
    assert budget_module.user_scopes(FAMILY[1], FAMILY, budgets) == ["Smith"]


def test_recipient_in_two_families_is_counted_once(budget_module):
    users = FAMILY + [_user("gina", ["Smith", "Jones"])]
    budgets = {"recipients": {"gina": _entry({"alice": 10, "carol": 10}, _expense("alice", 20))}, "settlements": []}
    assert budget_module.scope_transfers(budgets, "Jones", users) == [("carol", "alice", 1000)]
    assert budget_module.scope_transfers(budgets, "Smith", users) == []


def test_settle_minimises_transfers(budget_module):
    transfers = budget_module.settle({"a": -3000, "b": -1000, "c": 2500, "d": 1500})
    assert sum(amount for *_, amount in transfers) == 4000
    assert len(transfers) == 3


# --- budget routes -----------------------------------------------------------------------------

def test_set_and_remove_own_budget(client, env):
    login(client, "alice")
    response = client.post("/budget/bob", data={"amount": "25,5"})
    assert is_redirect_to(response, "/user_gift_ideas/bob")
    assert env.budgets()["recipients"]["bob"]["budgets"] == {"alice": 25.5}

    client.post("/budget/bob", data={"amount": ""})
    assert env.budgets()["recipients"]["bob"]["budgets"] == {}

    client.post("/budget/admin", data={"amount": ""})
    assert "admin" not in env.budgets()["recipients"]


def test_invalid_budget_is_refused(client, env):
    login(client, "alice")
    client.post("/budget/bob", data={"amount": "-3"})
    assert ("danger", "Montant invalide.") in flashes(client)
    assert env.budgets()["recipients"] == {}


@pytest.mark.parametrize("username, recipient", [
    ("bob", "bob"),             # the recipient never sees their own budget
    ("carol", "bob"),           # another family
    ("alice", "shared_smith"),  # shared lists have no budget
    ("alice", "guest_smith"),
])
def test_budget_routes_are_not_found_when_not_allowed(client, env, username, recipient):
    login(client, username)
    for path, data in ((f"/budget/{recipient}", {"amount": "10"}), (f"/budget/{recipient}/expense", {"amount": "10"}),
                       (f"/budget/{recipient}/expense/1/delete", {}), (f"/budget/{recipient}/reset", {})):
        assert client.post(path, data=data).status_code == 404, path
    assert env.budgets()["recipients"] == {}


def test_guests_cannot_use_budgets(client, env):
    login(client, "guest_smith")
    assert is_redirect_to(client.post("/budget/bob", data={"amount": "10"}), "/dashboard")
    assert is_redirect_to(client.get("/budget_overview"), "/dashboard")
    page = client.get("/user_gift_ideas/bob").get_data(as_text=True)
    assert 'id="budget"' not in page


def test_person_page_shows_shares_but_no_debts(client, env):
    _sharing(env, {"alice": 50, "carol": 30}, [_expense("alice", 42), _expense("carol", 8, id=2)])
    _en(client, "alice")
    page = client.get("/user_gift_ideas/bob").get_data(as_text=True)
    assert 'id="budget"' in page
    assert "31.25" in page and "18.75" in page and "+$10.75" in page
    assert "Mark as reimbursed" not in page


def test_recipient_never_sees_budget_on_table_view(client, env):
    _sharing(env, {"alice": 77.77})
    _en(client, "bob")
    assert "77.77" not in client.get("/table_view").get_data(as_text=True)

    other = env.module.app.test_client()
    _en(other, "alice")
    assert "77.77" in other.get("/table_view").get_data(as_text=True)


def test_free_expenses(client, env):
    _sharing(env, {"alice": 10})
    login(client, "alice")
    client.post("/budget/bob/expense", data={"amount": "8", "label": "Shipping"})
    expense = env.budgets()["recipients"]["bob"]["expenses"][0]
    assert (expense["paid_by"], expense["amount"], expense["label"], expense["idea_id"]) == ("alice", 8.0, "Shipping", None)

    other = env.module.app.test_client()
    login(other, "admin")  # sees bob's list, but did not pay this expense
    other.post(f"/budget/bob/expense/{expense['id']}/delete")
    assert len(env.budgets()["recipients"]["bob"]["expenses"]) == 1

    client.post(f"/budget/bob/expense/{expense['id']}/delete")
    assert env.budgets()["recipients"]["bob"]["expenses"] == []


def test_reset_one_recipient(client, env):
    _sharing(env, {"alice": 10}, [_expense("alice", 5)])
    login(client, "alice")
    client.post("/budget/bob/reset")
    assert env.budgets()["recipients"] == {}


def test_reset_one_recipient_is_refused_once_reimbursements_exist(client, env):
    _sharing(env, {"alice": 10}, [_expense("admin", 10)])
    budget = env.budgets()
    budget["settlements"].append({"id": 1, "scope": "Smith", "from": "alice", "to": "admin", "amount": 5, "date": ""})
    env.write_budgets(budget)
    login(client, "alice")
    client.post("/budget/bob/reset")
    assert "bob" in env.budgets()["recipients"]
    assert any(category == "warning" for category, _ in flashes(client))


# --- purchases ---------------------------------------------------------------------------------

def test_purchase_records_price_and_cancel_removes_it(client, env):
    login(client, "alice")
    client.post("/mark_as_bought/3", data={"price": "12,5"})
    (expense,) = env.budgets()["recipients"]["bob"]["expenses"]
    assert (expense["paid_by"], expense["amount"], expense["idea_id"], expense["individual"]) == ("alice", 12.5, 3, False)

    client.post("/mark_as_not_bought/3")
    assert env.budgets()["recipients"]["bob"]["expenses"] == []


def test_individual_gift_is_kept_out_of_the_split(client, env):
    login(client, "alice")
    client.post("/mark_as_bought/3", data={"price": "40", "individual": "on"})
    (expense,) = env.budgets()["recipients"]["bob"]["expenses"]
    assert expense["individual"] is True


def test_purchase_without_price_and_with_invalid_price(client, env):
    login(client, "alice")
    client.post("/mark_as_bought/3")
    assert env.budgets()["recipients"]["bob"]["expenses"][0]["amount"] is None
    client.post("/mark_as_not_bought/3")

    client.post("/mark_as_bought/3", data={"price": "abc"})
    assert env.idea(3)["bought_by"] == "alice"
    assert env.budgets()["recipients"]["bob"]["expenses"][0]["amount"] is None
    assert any(category == "warning" for category, _ in flashes(client))


def test_purchase_on_shared_list_records_nothing(client, env):
    env.update_idea(4, user_id="shared_smith")
    login(client, "alice")
    client.post("/mark_as_bought/4", data={"price": "10"})
    assert env.idea(4)["bought_by"] == "alice"
    assert env.budgets()["recipients"] == {}


def test_buyer_updates_purchase(client, env):
    login(client, "bob")  # bob bought idea 2, for alice
    response = client.post("/update_purchase/2", data={"price": "99", "individual": "on"})
    assert is_redirect_to(response, "/bought_items")
    (expense,) = env.budgets()["recipients"]["alice"]["expenses"]
    assert (expense["amount"], expense["individual"]) == (99.0, True)
    assert 'value="99.00"' in client.get("/bought_items").get_data(as_text=True)


def test_only_the_buyer_updates_a_purchase(client, env):
    login(client, "admin")
    client.post("/update_purchase/2", data={"price": "99"})
    assert ("danger", "Idée non trouvée") in flashes(client)
    assert env.budgets()["recipients"] == {}


def test_purged_idea_keeps_its_price(client, env):
    env.update_idea(2, date_bought=(datetime.now() - timedelta(days=40)).strftime("%Y-%m-%d %H:%M:%S"))
    login(client, "bob")
    client.post("/update_purchase/2", data={"price": "30"})
    client.get("/rundl")
    assert all(idea["gift_idea_id"] != 2 for idea in env.ideas())
    assert env.budgets()["recipients"]["alice"]["expenses"][0]["amount"] == 30.0


def test_deleted_recipient_keeps_counting_in_their_family(client, env):
    login(client, "alice")
    client.post("/budget/bob", data={"amount": "20"})
    client.post("/budget/bob/expense", data={"amount": "40"})
    assert env.budgets()["recipients"]["bob"]["scope"] == "Smith"

    admin = env.module.app.test_client()
    login(admin, "admin")
    admin.post("/users", data={"username": "bob", "delete_user": "1"})
    budget = env.budgets()
    # Kept under a key a new account named bob cannot take
    assert "bob" not in budget["recipients"]
    assert [key.split(":")[:2] for key in budget["recipients"]] == [["deleted", "bob"]]
    users = env.users()
    assert env.module.scope_transfers(budget, "Smith", users) == []  # alice paid her own share


def test_scope_is_frozen_at_creation(client, env):
    login(client, "alice")
    client.post("/budget/bob", data={"amount": "10"})
    env.update_user("bob", groups=["Adams", "Smith"])  # Adams now sorts first
    assert env.budgets()["recipients"]["bob"]["scope"] == "Smith"
    budget_module = env.module
    budget = env.budgets()
    budget["recipients"]["bob"]["expenses"].append(_expense("admin", 10))
    assert budget_module.scope_transfers(budget, "Smith", env.users()) == [("alice", "admin", 1000)]
    assert budget_module.scope_transfers(budget, "Adams", env.users()) == []


def test_free_expense_without_label_is_translated_when_shown(client, env):
    login(client, "alice")
    client.post("/budget/bob/expense", data={"amount": "5"})
    assert env.budgets()["recipients"]["bob"]["expenses"][0]["label"] == ""
    client.get("/set_language/en")
    assert "Other expense" in client.get("/user_gift_ideas/bob").get_data(as_text=True)


@pytest.mark.parametrize("remove", ["rundl", "delete"])
def test_removed_idea_id_reused_by_a_new_idea_does_not_take_its_price(client, env, remove):
    login(client, "bob")
    client.post("/update_purchase/2", data={"price": "30"})  # bob bought idea 2 (for alice)
    if remove == "rundl":
        env.update_idea(2, date_bought=(datetime.now() - timedelta(days=40)).strftime("%Y-%m-%d %H:%M:%S"))
        client.get("/rundl")
    else:
        assert client.delete("/delete_idea/2").status_code == 204  # bob added it
    (expense,) = env.budgets()["recipients"]["alice"]["expenses"]
    assert (expense["amount"], expense["idea_id"]) == (30.0, None)

    # A new idea gets id 2 again; buying and cancelling it leaves the old price alone
    ideas = env.ideas()
    ideas.append(dict(env.idea(3), gift_idea_id=2, gift_name="New idea", bought_by=None))
    env.write_ideas(ideas)
    other = env.module.app.test_client()
    login(other, "alice")
    other.post("/mark_as_bought/2", data={"price": "5"})
    other.post("/mark_as_not_bought/2")
    assert env.budgets()["recipients"]["alice"]["expenses"] == [expense]


# --- family overview ---------------------------------------------------------------------------

def test_overview_lists_my_debts_without_gift_details(client, env):
    # For bob: alice paid 40 for the "Secret telescope"; admin (no family) owes her his share
    env.write_budgets({"recipients": {"bob": _entry({"alice": 10, "admin": 10},
                                                    dict(_expense("alice", 40), label="Secret telescope"))},
                       "settlements": []})
    _en(client, "admin")
    page = client.get("/budget_overview?scope=Smith").get_data(as_text=True)
    assert "Secret telescope" not in page
    assert "To Alice Smith" in page and "$10.00" in page  # 40 spent, budgets 10 + 10: the 20 uncovered stay with alice


def test_settle_records_reimbursement(client, env):
    _sharing(env, {"alice": 20, "admin": 20}, [_expense("alice", 40)])
    login(client, "admin")
    assert "Smith" in client.get("/budget_overview").get_data(as_text=True)

    response = client.post("/budget_overview/settle", data={"scope": "Smith", "from": "admin", "to": "alice", "amount": "5"})
    assert is_redirect_to(response, "/budget_overview")
    assert env.budgets()["settlements"][0]["amount"] == 5.0

    # More than what is due is refused; an empty amount settles the rest
    client.post("/budget_overview/settle", data={"scope": "Smith", "from": "admin", "to": "alice", "amount": "16"})
    assert len(env.budgets()["settlements"]) == 1
    client.post("/budget_overview/settle", data={"scope": "Smith", "from": "admin", "to": "alice"})
    assert [s["amount"] for s in env.budgets()["settlements"]] == [5.0, 15.0]


def test_only_the_two_people_concerned_settle(client, env):
    _sharing(env, {"alice": 20, "admin": 20}, [_expense("alice", 40)])
    login(client, "bob")  # in Smith, but neither the debtor nor the creditor
    client.post("/budget_overview/settle", data={"scope": "Smith", "from": "admin", "to": "alice"})
    assert env.budgets()["settlements"] == []

    other = env.module.app.test_client()
    login(other, "carol")  # not in Smith and not involved
    assert other.post("/budget_overview/settle", data={"scope": "Smith", "from": "admin", "to": "alice"}).status_code == 404


def test_outsider_only_sees_own_transfers_and_cannot_close(client, env):
    # carol (Jones) paid for bob (Smith); alice and admin owe her and each other
    env.write_budgets({"recipients": {
        "bob": _entry({"alice": 10, "carol": 10, "admin": 10}, _expense("carol", 15), _expense("admin", 15, id=2))},
        "settlements": []})
    _en(client, "carol")
    page = client.get("/budget_overview?scope=Smith").get_data(as_text=True)
    assert "From Alice Smith" in page
    assert "Admin User →" not in page and "Alice Smith →" not in page  # the family-wide list is hidden
    assert "Close the family" not in page
    assert client.post("/budget_overview/close", data={"scope": "Smith"}).status_code == 404
    assert "bob" in env.budgets()["recipients"]


def test_close_family(client, env):
    env.write_budgets({"recipients": {"bob": _entry({"alice": 10}), "carol": _entry({"admin": 10})},
                       "settlements": [{"id": 1, "scope": "Smith", "from": "a", "to": "b", "amount": 1, "date": ""}]})
    login(client, "alice")
    client.post("/budget_overview/close", data={"scope": "Smith"})
    assert env.budgets() == {"recipients": {"carol": _entry({"admin": 10})}, "settlements": []}


def test_admin_resets_all_budgets(client, env):
    _sharing(env, {"alice": 10})
    login(client, "admin")
    assert is_redirect_to(client.post("/reset_all_budgets"), "/setup_advanced")
    assert env.budgets() == {"recipients": {}, "settlements": []}


def test_feature_can_be_disabled(client, env):
    _sharing(env, {"alice": 10})
    env.set_env("ENABLE_BUDGET", "false")
    login(client, "alice")
    assert client.get("/budget_overview").status_code == 404
    assert client.post("/budget/bob", data={"amount": "5"}).status_code == 404
    assert 'id="budget"' not in client.get("/user_gift_ideas/bob").get_data(as_text=True)
    client.post("/mark_as_bought/3", data={"price": "10"})
    assert env.budgets()["recipients"]["bob"]["expenses"] == []


def test_admin_toggles_the_feature(client, env):
    login(client, "admin")
    client.post("/update_budget_setting", data={"enable_budget": "false"})
    assert "ENABLE_BUDGET='false'" in env.env_file.read_text()


def test_budget_block_is_reachable_on_a_list_without_ideas(client, env):
    env.write_ideas([idea for idea in env.ideas() if idea["user_id"] != "bob"])
    login(client, "alice")
    response = client.get("/user_gift_ideas/bob")
    assert response.status_code == 200 and 'id="budget"' in response.get_data(as_text=True)

    # Without the budget block (feature off), the former redirection is kept
    env.set_env("ENABLE_BUDGET", "false")
    assert is_redirect_to(client.get("/user_gift_ideas/bob"), "/noidea")


def test_no_family_scope_cannot_be_closed_from_the_overview(client, env):
    # dan has no family; alice (Smith) and admin share his gift
    users = env.users()
    users.append(dict(env.user("carol"), username="dan", full_name="Dan", groups=[]))
    env.write_users(users)
    entry = dict(_entry({"alice": 10, "admin": 10}, _expense("alice", 20)), scope="__all__")
    env.write_budgets({"recipients": {"dan": entry}, "settlements": []})

    for username in ("alice", "admin"):  # involved; admin has no family either
        other = env.module.app.test_client()
        login(other, username)
        assert "budget_overview/close" not in other.get("/budget_overview?scope=__all__").get_data(as_text=True)
        assert other.post("/budget_overview/close", data={"scope": "__all__"}).status_code == 404
    assert "dan" in env.budgets()["recipients"]


def test_deleted_payer_keeps_their_credit_under_a_retired_name(client, env):
    _sharing(env, {"alice": 10, "admin": 10}, [_expense("admin", 20)])
    env.update_user("admin", groups=["Smith"])  # so that another admin is not needed below
    users = env.users()
    users.append(dict(env.user("admin"), username="root"))
    env.write_users(users)
    root = env.module.app.test_client()
    login(root, "root", PASSWORDS["admin"])
    root.post("/users", data={"username": "admin", "delete_user": "1"})

    budget = env.budgets()
    (payer,) = {e["paid_by"] for e in budget["recipients"]["bob"]["expenses"]}
    assert payer.startswith("deleted:admin:") and set(budget["recipients"]["bob"]["budgets"]) == {"alice", payer}
    assert all(e["idea_id"] is None for e in budget["recipients"]["bob"]["expenses"])
    _en(client, "alice")
    page = client.get("/budget_overview").get_data(as_text=True)
    assert "To admin" in page and "$10.00" in page


def test_bought_idea_without_recorded_price_shows_an_empty_field(client, env):
    login(client, "bob")  # idea 2 was bought before the feature: no expense
    page = client.get("/bought_items").get_data(as_text=True)
    assert 'name="price" class="p-2 border rounded inputer"\n                                   value=""' in page.replace("\r\n", "\n")
