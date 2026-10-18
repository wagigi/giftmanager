# CLAUDE.md

Guidance for working in this repository.

## Overview

Giftmanager is a self-hosted family gift-list web app: users post gift ideas for themselves or others, mark ideas as bought (hidden from the recipient to keep surprises), run Secret Santa draws, share lists by public link, and manage families/groups. It is a PWA (manifest + service worker) with dark mode and i18n (en, fr, nl, sv).

## Stack

- **Backend:** Flask. `app/app.py` (~2300 lines) creates the app and holds its config, Babel, OAuth, context processors, error handlers and all routes; the non-route helpers live in small flat modules next to it (see Layout), imported without a package prefix (`from storage import load_users`) because gunicorn runs `app:app` from `/app` and dev runs `flask --app app run` from `app/`. Helper modules never import `app` (use `flask.current_app` or `config`). No blueprints, no ORM, no database.
- **Storage:** flat JSON files, read and rewritten in full on every request (`load_users()` / `save_users()`, `load_gift_ideas()` / `save_gift_ideas()` in `storage.py`, paths taken from `current_app.config['USERS_FILE']` / `['IDEAS_FILE']`). There is no locking, which is why gunicorn runs with a single worker (`-w 1 --threads 4`). Keep it that way unless storage changes.
- **Templates:** Jinja2 in `app/templates/`, one standalone HTML page per view (no base layout; each page carries its own `<head>`, inline CSS variables for light/dark theme, Tailwind 2 and Font Awesome from CDN). The shared partials are `_language_switcher.html` and `_idea_age.html` (macro `idea_age_badge(idea, tag, css_class)`, imported `with context`: clock icon + idea age in a wrapper element, nothing without a readable date, shown on `/user_gift_ideas`, `/my_ideas`, `/table_view`, `/bought_items` and `/shared/<token>`).
- **Auth:** local passwords hashed with argon2 (`argon2-cffi`), plus optional OIDC via Authlib (`/login_oidc`, `/auth`).
- **Email:** Mailjet (`get_mailjet_client()` returns `None` when keys are unset, so email is optional).
- **Other deps:** BeautifulSoup + requests (fetch `og:image` previews for gift links), Pillow (avatar upload, cropped to 256px JPEG), Flask-Babel.

## Layout

```
app/
  app.py               # Flask app, config, Babel, OAuth, context processors, error handlers, all routes
  config.py            # DATA_DIR, dotenv_path, load_dotenv, first-start files (prepopulate_file), read_env_variable, set_env_variable, SUPPORTED_LANGUAGES
  storage.py           # load/save users.json and ideas.json, find_idea_by_id, get_user_email_by_username, get_full_name
  auth.py              # argon2 hasher (ph, password_hash, verify_password), login_required, admin_required, guest_allowed
  visibility.py        # get_visible_users, can_view_list, can_modify_idea, get_visible_groups
  mailer.py            # get_mailjet_client, send_email_to_buyer_via_mailjet (not email.py: it would shadow the stdlib)
  avatars.py           # UPLOADED_AVATAR_PREFIX, AVATAR_SIZE, avatar_url, delete_uploaded_avatar
  og_image.py          # fetch_og_image (the helper behind /fetch_og_image)
  cleanup.py           # get_delete_days, find_gift_ideas_to_delete, delete_gift_ideas, delete_old_gift_ideas
  currency.py          # get_currency_symbol, get_currency_position, format_currency
  sharing.py           # generate_share_token, generate_share_url, link_sharing_enabled, find_share_link
  idea_dates.py        # backfill_missing_dates, migrate_ideas_file (startup), idea_age (age label shown on idea pages)
  budget.py            # budgets per giver/recipient: recipient_split (shares, balances), scope_transfers (family offset), purchases
  requirements.txt     # unpinned dependencies
  templates/           # one template per page
  static/              # icons, avatars, bg image, manifest.json, sw.js
  translations/        # Babel .po/.mo per language + messages.pot
  users.json, ideas.json, .env   # local dev data (test data only, see below; budgets.json is created there by a dev run, gitignored)
babel.cfg              # extraction config for pybabel
requirements-dev.txt   # app requirements + pytest
pyproject.toml         # pytest config only (testpaths, pythonpath)
tests/                 # pytest smoke tests (conftest.py builds a temp DATA_DIR)
Dockerfile, docker-compose.yml
data/                  # docker volume (gitignored)
```

## Data directory and configuration

- `DATA_DIR` (env var) holds `.env`, `users.json`, `ideas.json`, `budgets.json`, `avatars/`, `santa_inst_<pool>.txt` and `last_execution_time.txt`. It defaults to the `app/` directory; in Docker it is `/app/data`, mounted from `./data`.
- On startup (when `config.py` is imported) `prepopulate_file()` creates default `ideas.json`, an empty `users.json`, an empty `budgets.json` and a default `.env` if missing.
- Configuration lives in `DATA_DIR/.env`, which admin pages **write back to** at runtime with `dotenv.set_key()`. Write settings with `set_key()` or `set_env_variable()` only (never by hand) and read runtime-editable ones with `read_env_variable(key, default)` rather than `os.getenv` (only reflects values loaded at startup). `read_env_variable` re-reads the file on each call with `dotenv_values(interpolate=False)`, so quoting, escapes, inline comments and duplicate keys (last wins) match `set_key()`; an empty value returns `default`, and a key missing from the file falls back to the process environment. Lines python-dotenv cannot parse (values with unescaped quotes written by older versions of the email settings and login message pages) are still read with the former rules; those two pages save through `set_env_variable()`, which replaces such a line instead of keeping it next to the new one. Only a few keys still use `os.getenv` and need a restart: `DATA_DIR`, `SECRET_KEY` (`app.config`) and `OIDC_CLIENT_ID` / `OIDC_CLIENT_SECRET` / `OIDC_SERVER_METADATA_URL` (the OAuth client is registered once at import with the values kept in `OIDC_STARTUP_SETTINGS`, which `/login` also uses to decide whether to show the OIDC button). Don't call `load_dotenv(override=True)` at runtime: it would make `os.environ` disagree with what was loaded at startup. `/setup_oidc` (on save) and `/setupenv` warn the admin when the saved values differ from them.
- Keys: `SECRET_KEY`, `MAILJET_API_KEY`, `MAILJET_API_SECRET`, `SYSTEM_EMAIL`, `DELETE_DAYS`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`, `OIDC_SERVER_METADATA_URL`, `OIDC_LOGOUT_URL`, `PRIMARY_OIDC_FIELD`, `SECONDARY_OIDC_FIELD`, `PRIMARY_DB_FIELD`, `SECONDARY_DB_FIELD`, `ENABLE_AUTO_REGISTRATION`, `ENABLE_DEFAULT_LOGIN`, `LOGIN_PAGE_MESSAGE`, `REORDERING`, `IMGENABLED`, `ENABLE_LINK_SHARING`, `ENABLE_SELF_REGISTRATION`, `JOINING_CODE`, `CURRENCY_SYMBOL`, `CURRENCY_POSITION`, `ENABLE_BUDGET`.
- The tracked `app/users.json`, `app/ideas.json` and `app/.env` are local dev/test fixtures (fake users), excluded from the Docker image by `.dockerignore`. Don't put real secrets in them.

## Data model

Everything is a list of dicts in JSON.

**User** (`users.json`): `username`, `password` (argon2 hash), `email`, `full_name`, `birthday`, `avatar` (`icons/avatarN.png` or `avatars/<file>` for uploads), `admin`, optional `groups` (families), `assigned_users` (`{pool_name: username}` for Secret Santa), `sharing.public_links[]` (`token`, `expires_at`, `is_active`).
The same list also holds two special kinds of entries:
- **Guests:** `guest: true`, `access_type` (`family` → see `groups`; `people` → see `access_users`). Only routes decorated with `@guest_allowed` are reachable by guests.
- **Shared lists:** `shared_list: true`, username `shared_<name>`, `list_members[]`. A collaborative list that members can edit like their own.

**Idea** (`ideas.json`): `gift_idea_id` (int, max+1), `user_id` (recipient username), `gift_name`, `description`, `link`, `value`, `added_by`, `bought_by`, `image_path`, `date_added`, `date_bought` (both `%Y-%m-%d %H:%M:%S`), optional `date_added_unknown` / `date_bought_unknown`. Older versions did not record these dates: at startup `migrate_ideas_file()` gives the current date to ideas missing `date_added` (except the seeded `demo` placeholder, so the age-based purge keeps skipping it) (and to bought ideas missing `date_bought`, which `/rundl` could otherwise never purge) and sets the matching `_unknown` flag; the age is then shown as "More than N days" with an explanation on hover. Marking an idea bought or not bought drops `date_bought_unknown`. Order for the reorder feature is persisted via `/update_order`. The seeded `demo` idea is a placeholder ("dont delete").

**Budgets** (`budgets.json`, `load_budgets()` / `save_budgets()`): `{"recipients": {username: {"scope": family, "budgets": {giver: amount}, "expenses": [...]}}, "settlements": [...]}`. An expense is `id`, `paid_by`, `amount` (float, or `None` when the buyer gave no price), `label`, `idea_id` (`None` for a free expense such as shipping), `individual`, `date`; a settlement (reimbursement) is `id`, `scope`, `from`, `to`, `amount`, `date`. Buying an idea records its price here (`record_idea_purchase`); cancelling the purchase removes it. When an idea is deleted or purged, `detach_ideas` sets its expense's `idea_id` to `None` (the amount stays, and a new idea reusing the id does not take it over). Computations are in integer cents (`to_cents`, `format_money(cents)` in templates). Per recipient, the shared cost (expenses not marked `individual`) is split in proportion to the budgets > 0; above their sum each giver pays their full budget and the uncovered rest stays with the payers. Balances of all the recipients of a family are offset into the transfers shown on `/budget_overview`. An entry's family is set when it is created (`recipient_scope()`: the recipient's first family alphabetically, or `__all__` without one, so nobody is counted twice) and never changes afterwards, so recorded reimbursements stay consistent; entries of deleted users are kept for the same reason. Resetting one recipient is refused once reimbursements exist in its family (close the family instead). Only regular accounts take part (no guests, shared lists, share-link visitors).

## Access control

- `@login_required` redirects anonymous users and blocks guests unless the view is also wrapped by `@guest_allowed` (it checks the `_guest_allowed` attribute on the wrapped function, so put `@login_required` above `@guest_allowed`).
- `@admin_required` checks `admin` on the user record. Both decorators clear the session and redirect to `/login` when the session's account no longer exists (deleted user or guest).
- Visibility of other users' lists is computed by `get_visible_users()` from groups (users without groups see everyone non-guest; users with groups see shared-group members and group-less users; family guests see members of their `groups`, people guests their `access_users`). `can_view_list(current_user, username, users)` (own list, a visible one, or a shared list the user is a member of) guards the routes that open or act on someone else's list: `/user_gift_ideas` (flash + redirect to the dashboard), `/mark_as_bought` (treated as not found), `/add_idea` and `/add2` POST (their recipient dropdowns list the users `can_view_list` accepts). `/table_view` shows the lists `can_view_list` accepts (no guests). `/edit_idea` and `/delete_idea` rely on ownership instead (`can_modify_idea()`: adder or shared-list member; anyone else, the recipient included, gets the same not-found answer as for an unknown id), `/mark_as_not_bought` on being the buyer (other ideas the user cannot see, or on their own list, are reported as not found), and `/update_order` only reorders ideas the user added to their own list.
- Recipients must never see who bought their own gifts, nor whether they were bought, nor the ideas others added for them; preserve this when touching idea views. Their own list is shown as on `/my_ideas` (only ideas they added, no bought state) in `/table_view` and when they open their own share link while logged in; `/mark_as_bought` on one's own idea is always refused with the same message.
- Budgets (`can_see_budget()`): a recipient never sees the budget block of their own list, nor its summary in `/table_view`; the budget routes answer 404 to them. `/budget_overview` shows only net transfers between people (no gift, no recipient), and includes the lists the viewer is the recipient of. A user also sees the families where they owe or are owed money, but only their own transfers there. Settlements can only be recorded by the debtor or the creditor, up to the amount due; only members of a family (or an admin) can close it; for the `__all__` scope, which has no real members, the people involved in it can. `/user_gift_ideas` no longer redirects to `/noidea` when the budget block is shown, so it stays reachable on a list without ideas.
- Public share links: `/shared/<token>` and its mark-bought/not-bought routes are unauthenticated and all gated the same way (`ENABLE_LINK_SHARING`, link active and not expired) through `find_share_link()` in `sharing.py`.
- `/fetch_og_image` requires a logged-in non-guest user (it fetches arbitrary URLs server-side).

## Main features → routes

- Setup wizard on empty install: `/setupadmin` → `/setupenv` (unauthenticated; only reachable once, in the session that just created the first admin on `/setupadmin`).
- Auth: `/login`, `/logout`, `/register` (self-registration), `/login_oidc`, `/auth` (OIDC callback; auto-registration names the account after `preferred_username` and refuses a missing or already taken one), `/setup_profile`, `/guest_login`.
- Ideas: `/dashboard`, `/my_ideas`, `/user_gift_ideas/<user>`, `/add_idea/<user>`, `/add2/`, `/edit_idea/<id>`, `/delete_idea/<id>` (DELETE), `/mark_as_bought/<id>`, `/mark_as_not_bought/<id>`, `/bought_items`, `/table_view`, `/update_order`, `/fetch_og_image`.
- Budgets: `/budget/<user>` (my budget), `/budget/<user>/expense`, `/budget/<user>/expense/<id>/delete`, `/budget/<user>/reset`, `/update_purchase/<id>` (buyer: price paid, individual gift), `/budget_overview` (family offset, `?scope=`), `/budget_overview/settle`, `/budget_overview/close`. `/mark_as_bought` takes optional `price` and `individual` form fields (purchase popup on `/user_gift_ideas`).
- Profile: `/change_password`, `/change_email`, `/change_avatar`, `/avatars/<file>`.
- Secret Santa: `/secret_santa` (admin; simple shuffled cycle per pool), `/secret_santa_assignments`.
- Sharing: `/manage_sharing`, `/manage_shared_lists`, `/shared/<token>`.
- Admin: `/admin`, `/users`, `/families`, `/manage_guest_users`, `/edit_email_settings`, `/edit_login_message`, `/setup_oidc`, `/setup_advanced` (incl. `/update_budget_setting`, `/reset_all_budgets`), `/delete_old_gift_ideas`, `/change_delete_days`, `/rundl` (purges bought ideas older than `DELETE_DAYS`, default 30 when unset or invalid (not an integer from 1 to 36500), skipping ideas with malformed dates; unauthenticated, meant to be hit by an external cron).
- `/set_language/<code>` stores the locale in the session.

The app version string is hard-coded in `dashboard()` (`app_version = "v2.6.2"`); bump it on release.

## Running

Local:
```bash
python -m venv venv && source venv/bin/activate
pip install -r app/requirements.txt
cd app && flask --app app run --debug        # http://localhost:5000
```
Without `DATA_DIR` set, data files are read/written inside `app/`.

Docker:
```bash
docker compose up --build    # data persisted in ./data
```

## Tests

Smoke tests live in `tests/` at the repo root (outside `app/`, so the Docker image doesn't ship them):
```bash
pip install -r requirements-dev.txt && pytest    # from the repo root
```
- `tests/conftest.py` builds a temporary `DATA_DIR` per test (`.env`, `users.json`, `ideas.json` with an admin, two users in family Smith, one in family Jones, a family guest and a shared list), sets `DATA_DIR` and then (re)imports `app` and every module it loaded from `app/` (`config`, `storage`...), because `config.py` reads the data directory at import time. Patch names where they are used: `mailer.Client`, `og_image.requests` (fixtures `mailer_module`, `og_image_module`; `budget_module` gives the pure cost-sharing functions). The tracked `app/users.json`, `app/ideas.json` and `app/.env` are never touched.
- Helpers in `tests/smoke_helpers.py`: `login(client, username)`, `is_redirect_to(response, path)`, `flashes(client)`, `session_username(client)` and the test passwords/tokens. The `env` fixture exposes the temp files (`env.users()`, `env.user(name)`, `env.ideas()`, `env.idea(id)`, `env.budgets()`, `env.write_budgets(...)`, `env.update_user(...)`, `env.update_idea(...)`, `env.update_share_link(...)`, `env.set_env(key, value)`, which only affects keys read with `read_env_variable`). Flash messages and page text are in French unless the test calls `/set_language/en` first.
- Tests freeze current behavior. Confirmed bugs are kept as strict `xfail` tests (remove the marker when fixing one). Questionable behavior whose fix is not decided yet (e.g. security holes) is asserted as-is, in a test whose docstring starts with `CURRENT BEHAVIOR`; update that test when the behavior changes.
- No network: an autouse fixture makes socket connections fail; `requests.get` is mocked for `/fetch_og_image`, Mailjet keys are empty (or `mailer.Client` is mocked when a test sets them), OIDC is not configured (`tests/test_runtime_config.py` mocks the provider calls on `oauth.keycloak` to exercise `/auth`).

There are no linters or CI configured.

## Translations (Flask-Babel)

Wrap user-facing strings with `_()` in Python (use named placeholders: `_('Pool "%(name)s"', name=x)`) and `{{ _('...') }}` in templates. After changing strings:
```bash
pybabel extract -F babel.cfg -k _l -o app/translations/messages.pot .
pybabel update -i app/translations/messages.pot -d app/translations
# edit the .po files for fr, nl, sv
pybabel compile -d app/translations
```
Commit both `.po` and compiled `.mo` files. `BABEL_DEFAULT_LOCALE` is `fr`; the request locale comes from the session or `Accept-Language`. New languages must also be added to `SUPPORTED_LANGUAGES` in `config.py`. `babel.cfg` extracts from every `app/**.py`, so strings in the helper modules are included.

## Conventions

- Follow the existing style: routes as plain functions in `app.py`, non-route helpers in the matching module (no `import app` from a module), `flash(_('...'), category)` + `redirect(url_for(...))` after POSTs, load-modify-save of the whole JSON file.
- When adding a new runtime setting, give it a default in `prepopulate_file(dotenv_path, ...)` if appropriate and read it with `read_env_variable`.
- If you add static assets that should work offline, add them to `urlsToCache` in `app/static/sw.js` and bump `CACHE_NAME`.

## Development process

- Before opening any pull request, have the changes reviewed by an agent by running `/code-review` on the branch. Fix the findings that hold up (or note why one is dismissed) before creating the PR.
- This is enforced by a Claude Code hook (`.claude/settings.json` → `.claude/hooks/require-code-review.sh`): a `/code-review` of the current branch with a clean tree records HEAD in `.git/claude-code-review-head` once it has finished (interrupted or failed reviews don't count), and `gh pr create` / `gh pr new` is denied unless that commit is the current HEAD. Commit before reviewing; any new commit (including review fixes) needs another `/code-review`. It only guards Claude Code; it is not a security boundary.
- Every PR description on GitHub (the body passed to `gh pr create`) starts with a short summary of the feature: **What** changed, **How** it was done, **Why** it was needed. Keep each part to a few simple bullet points.
- When the PR adds or changes a user-visible feature, the description also has a **Screenshots** section showing what was asked for, one captioned image per affected page (light theme by default, plus dark or mobile width when the change touches them). Pure refactors, fixes without UI change and test-only PRs skip it.
  - Take them from the real app (see the `run` skill) started with a throwaway `DATA_DIR` holding fake users and ideas (e.g. copied from `app/users.json` / `app/ideas.json`, with ideas added to show the feature), never from `data/`. Headless Playwright works for pages behind login (`pip install playwright && playwright install firefox`, kept out of `requirements-dev.txt`).
  - GitHub has no API to attach images to a PR body, so push the PNGs to the orphan branch `pr-screenshots`, under a folder named after the PR branch (`feat/idea-age/…`), and embed them with `![caption](https://raw.githubusercontent.com/wagigi/giftmanager/pr-screenshots/<branch>/<file>.png)`. Create the branch on first use with `git switch --orphan pr-screenshots` (in a separate worktree so the feature branch stays untouched).
