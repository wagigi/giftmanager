"""Budgets per giver and recipient, cost sharing and family settlement (budgets.json).

budgets.json holds {"recipients": {username: {"scope": family, "budgets": {giver: amount}, "expenses": [...]}},
"settlements": [...]}. Amounts are stored as floats with 2 decimals and computed in integer cents.
The recipient of a list never sees its entry (surprise rule); the family overview only shows net
transfers between people, never gifts or recipients.
"""
import math
from datetime import datetime

from config import read_env_variable
from visibility import can_view_list

ALL_SCOPE = '__all__'  # Scope of the recipients who are in no family
MAX_AMOUNT = 1_000_000


def budget_enabled():
    return read_env_variable("ENABLE_BUDGET", "true").lower() == 'true'


def empty_budgets():
    return {'recipients': {}, 'settlements': []}


def is_budget_user(user):
    """Regular accounts only: guests and shared lists have no budget and are not recipients."""
    return bool(user) and not user.get('guest') and not user.get('shared_list')


def can_see_budget(current_user, recipient_username, users):
    """True if current_user may see and edit the budget of recipient_username's list (never their own)."""
    if not is_budget_user(current_user) or recipient_username == current_user['username']:
        return False
    recipient = next((user for user in users if user['username'] == recipient_username), None)
    return is_budget_user(recipient) and can_view_list(current_user, recipient_username, users)


def parse_amount(text):
    """Amount typed in a form ('12,50', '12.5', ' 8 ') as a float with 2 decimals, or None if blank or invalid."""
    text = (text or '').strip().replace(',', '.')
    for space in (' ', '\u00a0', '\u202f'):  # thousands separators ('1 234,50')
        text = text.replace(space, '')
    if not text:
        return None
    try:
        amount = float(text)
    except ValueError:
        return None
    if not math.isfinite(amount) or amount < 0 or amount > MAX_AMOUNT:
        return None
    return round(amount, 2)


def to_cents(amount):
    return int(round((amount or 0) * 100))


def format_cents(cents):
    """Cents as a plain decimal string ('31.25'), to pass to format_currency()."""
    sign = '-' if cents < 0 else ''
    cents = abs(cents)
    return f"{sign}{cents // 100}.{cents % 100:02d}"


def recipient_entry(budgets, recipient, create_for=None):
    """The entry of a recipient's list, created when missing if create_for (the recipient's user
    record) is given. Its family is set at creation and never changes, so the reimbursements
    recorded in that family stay consistent when the recipient's families change later."""
    entry = budgets['recipients'].get(recipient)
    if entry is None and create_for is not None:
        entry = budgets['recipients'][recipient] = {'scope': recipient_scope(create_for), 'budgets': {}, 'expenses': []}
    return entry


def _next_id(items):
    return max((item['id'] for item in items), default=0) + 1


def _now():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _allocate(total, weights):
    """Split `total` cents in proportion to `weights` (largest remainder: the parts add up to total)."""
    weight_sum = sum(weights.values())
    if total <= 0 or weight_sum <= 0:
        return {key: 0 for key in weights}
    parts = {key: total * weight // weight_sum for key, weight in weights.items()}
    remainders = sorted(weights, key=lambda key: (-(total * weights[key] % weight_sum), key))
    for key in remainders[:total - sum(parts.values())]:
        parts[key] += 1
    return parts


def recipient_split(entry):
    """Shares and balances (in cents) of the people involved in one recipient's gifts.

    The shared cost is the sum of the expenses not marked individual. Givers with a budget > 0
    pay it in proportion to their budgets; when it exceeds the sum of the budgets, each pays their
    full budget and the uncovered rest stays with the payers, in proportion to what they are owed.
    A balance is positive when the person is owed money."""
    entry = entry or {'budgets': {}, 'expenses': []}
    budgets = {user: to_cents(amount) for user, amount in entry.get('budgets', {}).items() if to_cents(amount) > 0}
    shared = [e for e in entry.get('expenses', []) if not e.get('individual')]
    individual = [e for e in entry.get('expenses', []) if e.get('individual')]

    paid = {}
    for expense in shared:
        paid[expense['paid_by']] = paid.get(expense['paid_by'], 0) + to_cents(expense.get('amount'))

    total_spent = sum(paid.values())
    total_budget = sum(budgets.values())
    if total_spent <= total_budget:
        shares = _allocate(total_spent, budgets)
        uncovered = 0
    else:
        shares = dict(budgets)
        uncovered = total_spent - total_budget

    people = sorted(set(budgets) | set(paid))
    balances = {user: paid.get(user, 0) - shares.get(user, 0) for user in people}
    if uncovered:
        owed = {user: balance for user, balance in balances.items() if balance > 0}
        for user, part in _allocate(uncovered, owed).items():
            balances[user] -= part

    return {
        'budgets': budgets,
        'total_budget': total_budget,
        'total_spent': total_spent,
        'individual_spent': sum(to_cents(e.get('amount')) for e in individual),
        'paid': paid,
        'shares': shares,
        'uncovered': uncovered,
        'balances': balances,
        'people': people,
    }


# --- Family overview -------------------------------------------------------------------------

def recipient_scope(user):
    """The one family a recipient's balances are counted in (the first one alphabetically, so a
    recipient in several families is never counted twice), or ALL_SCOPE when they have none."""
    return member_scopes(user)[0]


def entry_scope(recipient, entry, users_by_name):
    """Family an entry counts in: the one stored at creation, else (older entries) the recipient's
    current one. Entries of deleted users keep counting, so the money others paid is not lost."""
    if entry.get('scope'):
        return entry['scope']
    user = users_by_name.get(recipient)
    return recipient_scope(user) if user else None


def scope_balances(budgets, scope, users):
    """Net balance (cents) of every person over the recipients of `scope`, minus the
    reimbursements already recorded in that scope."""
    users_by_name = {user['username']: user for user in users}
    balances = {}
    for recipient, entry in budgets['recipients'].items():
        if entry_scope(recipient, entry, users_by_name) != scope:
            continue
        for person, balance in recipient_split(entry)['balances'].items():
            balances[person] = balances.get(person, 0) + balance
    for settlement in budgets['settlements']:
        if settlement['scope'] == scope:
            amount = to_cents(settlement['amount'])
            balances[settlement['from']] = balances.get(settlement['from'], 0) + amount
            balances[settlement['to']] = balances.get(settlement['to'], 0) - amount
    return balances


def settle(balances):
    """Transfers [(from, to, cents)] that bring every balance to zero: the largest debtor pays the
    largest creditor until one of them is even."""
    debtors = sorted(((-balance, person) for person, balance in balances.items() if balance < 0), reverse=True)
    creditors = sorted(((balance, person) for person, balance in balances.items() if balance > 0), reverse=True)
    debtors = [[amount, person] for amount, person in debtors]
    creditors = [[amount, person] for amount, person in creditors]
    transfers = []
    while debtors and creditors:
        amount = min(debtors[0][0], creditors[0][0])
        transfers.append((debtors[0][1], creditors[0][1], amount))
        debtors[0][0] -= amount
        creditors[0][0] -= amount
        if not debtors[0][0]:
            debtors.pop(0)
        if not creditors[0][0]:
            creditors.pop(0)
        debtors.sort(reverse=True)
        creditors.sort(reverse=True)
    return transfers


def scope_transfers(budgets, scope, users):
    return settle(scope_balances(budgets, scope, users))


def member_scopes(current_user):
    """The families current_user belongs to, or ALL_SCOPE when they have none."""
    return sorted(group for group in current_user.get('groups', []) if not group.startswith('guest_')) or [ALL_SCOPE]


def user_scopes(current_user, users, budgets):
    """Scopes current_user may open on the overview: their families (or ALL_SCOPE without one),
    plus any scope where they owe or are owed money or recorded a reimbursement (there they only
    see their own transfers)."""
    scopes = member_scopes(current_user)
    username = current_user['username']
    users_by_name = {user['username']: user for user in users}
    candidates = {entry_scope(recipient, entry, users_by_name) for recipient, entry in budgets['recipients'].items()}
    candidates |= {settlement['scope'] for settlement in budgets['settlements']}
    candidates.discard(None)
    scopes += [scope for scope in sorted(candidates - set(scopes)) if is_involved(budgets, scope, users, username)]
    return scopes


def is_involved(budgets, scope, users, username):
    """True if username owes or is owed money in scope, or recorded a reimbursement there."""
    return bool(scope_balances(budgets, scope, users).get(username)) or any(
        username in (s['from'], s['to']) for s in budgets['settlements'] if s['scope'] == scope)


def can_close_scope(current_user, scope):
    """Members of a family close it (not someone who once paid for one of its lists). The "no
    family" scope has no real members: only an admin's global reset clears it."""
    return scope != ALL_SCOPE and scope in member_scopes(current_user)


def close_scope(budgets, scope, users):
    """Forget the budgets, expenses and reimbursements of every recipient of `scope`."""
    users_by_name = {user['username']: user for user in users}
    budgets['recipients'] = {
        recipient: entry for recipient, entry in budgets['recipients'].items()
        if entry_scope(recipient, entry, users_by_name) != scope
    }
    budgets['settlements'] = [s for s in budgets['settlements'] if s['scope'] != scope]


def add_settlement(budgets, scope, payer, payee, amount):
    budgets['settlements'].append({
        'id': _next_id(budgets['settlements']), 'scope': scope, 'from': payer, 'to': payee,
        'amount': amount, 'date': _now(),
    })


# --- Expenses ---------------------------------------------------------------------------------

def add_expense(budgets, recipient_user, paid_by, amount, label, idea_id=None, individual=False):
    """Record an expense. An empty label is shown as "Other expense", in the reader's language."""
    entry = recipient_entry(budgets, recipient_user['username'], create_for=recipient_user)
    entry['expenses'].append({
        'id': _next_id(entry['expenses']), 'paid_by': paid_by, 'amount': amount, 'label': label,
        'idea_id': idea_id, 'individual': bool(individual), 'date': _now(),
    })


def find_idea_expense(budgets, idea_id):
    """(recipient, expense) recorded for a bought idea, or (None, None)."""
    for recipient, entry in budgets['recipients'].items():
        for expense in entry['expenses']:
            if expense.get('idea_id') == idea_id:
                return recipient, expense
    return None, None


def record_idea_purchase(budgets, recipient_user, idea, buyer, amount, individual):
    """Record (or replace) the price paid for a bought idea. The amount is kept here, so the
    shared cost does not change when /rundl later purges the idea."""
    remove_idea_purchase(budgets, idea['gift_idea_id'])
    add_expense(budgets, recipient_user, buyer, amount, idea.get('gift_name', ''),
                idea_id=idea['gift_idea_id'], individual=individual)


def remove_idea_purchase(budgets, idea_id):
    """Forget the price paid for an idea. True if there was one."""
    removed = False
    for entry in budgets['recipients'].values():
        kept = [e for e in entry['expenses'] if e.get('idea_id') != idea_id]
        removed = removed or len(kept) != len(entry['expenses'])
        entry['expenses'] = kept
    return removed


DELETED_PREFIX = 'deleted:'


def retire_user(budgets, user):
    """A deleted account keeps counting everywhere (its list, its budgets, the money it paid or
    was reimbursed), so the other balances do not change, but under a name no new account can
    take ('deleted:<username>:<date>'): a user later created with the same name starts empty.
    Returns False when the account appears nowhere."""
    username = user['username']
    retired = f"{DELETED_PREFIX}{username}:{_now()}"
    changed = False
    entry = budgets['recipients'].pop(username, None)
    if entry is not None:
        entry.setdefault('scope', recipient_scope(user))
        # The deleted user's ideas may remain: a new account with the same name must not take
        # over the purchases recorded on them
        for expense in entry['expenses']:
            expense['idea_id'] = None
        budgets['recipients'][retired] = entry
        changed = True
    for entry in budgets['recipients'].values():
        if username in entry['budgets']:
            entry['budgets'][retired] = entry['budgets'].pop(username)
            changed = True
        for expense in entry['expenses']:
            if expense['paid_by'] == username:
                expense['paid_by'] = retired
                expense['idea_id'] = None  # a new account with the same name must not take it over
                changed = True
    for settlement in budgets['settlements']:
        for side in ('from', 'to'):
            if settlement[side] == username:
                settlement[side] = retired
                changed = True
    return changed


def person_names(users):
    """Display names of the people in budgets.json, including retired (deleted) accounts."""
    class Names(dict):
        def get(self, key, default=None):
            if key in self:
                return self[key]
            if isinstance(key, str) and key.startswith(DELETED_PREFIX):
                return key.split(':')[1]
            return default
    return Names((user['username'], user.get('full_name') or user['username']) for user in users)


def detach_ideas(budgets, idea_ids):
    """Ideas deleted or purged: their expenses stay (the money was spent) but no longer point to
    the idea, whose id a new idea may reuse (ids are max + 1). They become free expenses.
    True if an expense was changed."""
    changed = False
    for entry in budgets['recipients'].values():
        for expense in entry['expenses']:
            if expense.get('idea_id') in idea_ids:
                expense['idea_id'] = None
                changed = True
    return changed

