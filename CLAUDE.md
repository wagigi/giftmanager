# CLAUDE.md

Guidance for working in this repository.

## Overview

Giftmanager is a self-hosted family gift-list web app: users post gift ideas for themselves or others, mark ideas as bought (hidden from the recipient to keep surprises), run Secret Santa draws, share lists by public link, and manage families/groups. It is a PWA (manifest + service worker) with dark mode and i18n (en, fr, nl, sv).

## Stack

- **Backend:** Flask. `app/app.py` (~2300 lines) creates the app and holds its config, Babel, OAuth, context processors, error handlers and all routes; the non-route helpers live in small flat modules next to it (see Layout), imported without a package prefix (`from storage import load_users`) because gunicorn runs `app:app` from `/app` and dev runs `flask --app app run` from `app/`. Helper modules never import `app` (use `flask.current_app` or `config`). No blueprints, no ORM, no database.
- **Storage:** flat JSON files, read and rewritten in full on every request (`load_users()` / `save_users()`, `load_gift_ideas()` / `save_gift_ideas()` in `storage.py`, paths taken from `current_app.config['USERS_FILE']` / `['IDEAS_FILE']`). There is no locking, which is why gunicorn runs with a single worker (`-w 1 --threads 4`). Keep it that way unless storage changes.
- **Templates:** Jinja2 in `app/templates/`, one standalone HTML page per view (no base layout; each page carries its own `<head>`, inline CSS variables for light/dark theme, Tailwind 2 and Font Awesome from CDN). The only shared partial is `_language_switcher.html`.
- **Auth:** local passwords hashed with argon2 (`argon2-cffi`), plus optional OIDC via Authlib (`/login_oidc`, `/auth`).
- **Email:** Mailjet (`get_mailjet_client()` returns `None` when keys are unset, so email is optional).
- **Other deps:** BeautifulSoup + requests (fetch `og:image` previews for gift links), Pillow (avatar upload, cropped to 256px JPEG), Flask-Babel.

## Layout

```
app/
  app.py               # Flask app, config, Babel, OAuth, context processors, error handlers, all routes
  config.py            # DATA_DIR, dotenv_path, load_dotenv, first-start files (prepopulate_file), read_env_variable, SUPPORTED_LANGUAGES
  storage.py           # load/save users.json and ideas.json, find_idea_by_id, get_user_email_by_username, get_full_name
  auth.py              # argon2 hasher (ph, password_hash, verify_password), login_required, admin_required, guest_allowed
  visibility.py        # get_visible_users, get_visible_groups
  mailer.py            # get_mailjet_client, send_email_to_buyer_via_mailjet (not email.py: it would shadow the stdlib)
  avatars.py           # UPLOADED_AVATAR_PREFIX, AVATAR_SIZE, avatar_url, delete_uploaded_avatar
  og_image.py          # fetch_og_image (the helper behind /fetch_og_image)
  cleanup.py           # find_gift_ideas_to_delete, delete_gift_ideas, delete_old_gift_ideas
  currency.py          # get_currency_symbol, get_currency_position, format_currency
  sharing.py           # generate_share_token, generate_share_url
  requirements.txt     # unpinned dependencies
  templates/           # one template per page
  static/              # icons, avatars, bg image, manifest.json, sw.js
  translations/        # Babel .po/.mo per language + messages.pot
  users.json, ideas.json, .env   # local dev data (test data only, see below)
babel.cfg              # extraction config for pybabel
requirements-dev.txt   # app requirements + pytest
pyproject.toml         # pytest config only (testpaths, pythonpath)
tests/                 # pytest smoke tests (conftest.py builds a temp DATA_DIR)
Dockerfile, docker-compose.yml
data/                  # docker volume (gitignored)
```

## Data directory and configuration

- `DATA_DIR` (env var) holds `.env`, `users.json`, `ideas.json`, `avatars/`, `santa_inst_<pool>.txt` and `last_execution_time.txt`. It defaults to the `app/` directory; in Docker it is `/app/data`, mounted from `./data`.
- On startup (when `config.py` is imported) `prepopulate_file()` creates default `ideas.json`, an empty `users.json` and a default `.env` if missing.
- Configuration lives in `DATA_DIR/.env`, which admin pages **write back to** at runtime with `dotenv.set_key()`. Read runtime-editable settings with `read_env_variable(key, default)` (re-reads the file each call) rather than `os.getenv` (only reflects values loaded at startup). Some older code still uses `os.getenv`; changes to those keys need a restart.
- Keys: `SECRET_KEY`, `MAILJET_API_KEY`, `MAILJET_API_SECRET`, `SYSTEM_EMAIL`, `DELETE_DAYS`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`, `OIDC_SERVER_METADATA_URL`, `OIDC_LOGOUT_URL`, `PRIMARY_OIDC_FIELD`, `SECONDARY_OIDC_FIELD`, `PRIMARY_DB_FIELD`, `SECONDARY_DB_FIELD`, `ENABLE_AUTO_REGISTRATION`, `ENABLE_DEFAULT_LOGIN`, `LOGIN_PAGE_MESSAGE`, `REORDERING`, `IMGENABLED`, `ENABLE_LINK_SHARING`, `ENABLE_SELF_REGISTRATION`, `JOINING_CODE`, `CURRENCY_SYMBOL`, `CURRENCY_POSITION`.
- The tracked `app/users.json`, `app/ideas.json` and `app/.env` are local dev/test fixtures (fake users), excluded from the Docker image by `.dockerignore`. Don't put real secrets in them.

## Data model

Everything is a list of dicts in JSON.

**User** (`users.json`): `username`, `password` (argon2 hash), `email`, `full_name`, `birthday`, `avatar` (`icons/avatarN.png` or `avatars/<file>` for uploads), `admin`, optional `groups` (families), `assigned_users` (`{pool_name: username}` for Secret Santa), `sharing.public_links[]` (`token`, `expires_at`, `is_active`).
The same list also holds two special kinds of entries:
- **Guests:** `guest: true`, `access_type` (`family` → see `groups`; `people` → see `access_users`). Only routes decorated with `@guest_allowed` are reachable by guests.
- **Shared lists:** `shared_list: true`, username `shared_<name>`, `list_members[]`. A collaborative list that members can edit like their own.

**Idea** (`ideas.json`): `gift_idea_id` (int, max+1), `user_id` (recipient username), `gift_name`, `description`, `link`, `value`, `added_by`, `bought_by`, `image_path`, `date_added`, `date_bought`. Order for the reorder feature is persisted via `/update_order`. The seeded `demo` idea is a placeholder ("dont delete").

## Access control

- `@login_required` redirects anonymous users and blocks guests unless the view is also wrapped by `@guest_allowed` (it checks the `_guest_allowed` attribute on the wrapped function, so put `@login_required` above `@guest_allowed`).
- `@admin_required` checks `admin` on the user record.
- Visibility of other users' lists is computed by `get_visible_users()` from groups (users without groups see everyone non-guest; users with groups see shared-group members and group-less users).
- Recipients must never see who bought their own gifts; preserve this when touching idea views.
- Public share links: `/shared/<token>` and its mark-bought routes are unauthenticated and gated by `ENABLE_LINK_SHARING` and link expiry.

## Main features → routes

- Setup wizard on empty install: `/setupadmin` → `/setupenv` (only reachable via Referer from setupadmin).
- Auth: `/login`, `/logout`, `/register` (self-registration), `/login_oidc`, `/auth`, `/setup_profile`, `/guest_login`.
- Ideas: `/dashboard`, `/my_ideas`, `/user_gift_ideas/<user>`, `/add_idea/<user>`, `/add2/`, `/edit_idea/<id>`, `/delete_idea/<id>` (DELETE), `/mark_as_bought/<id>`, `/mark_as_not_bought/<id>`, `/bought_items`, `/table_view`, `/update_order`, `/fetch_og_image`.
- Profile: `/change_password`, `/change_email`, `/change_avatar`, `/avatars/<file>`.
- Secret Santa: `/secret_santa` (admin; simple shuffled cycle per pool), `/secret_santa_assignments`.
- Sharing: `/manage_sharing`, `/manage_shared_lists`, `/shared/<token>`.
- Admin: `/admin`, `/users`, `/families`, `/manage_guest_users`, `/edit_email_settings`, `/edit_login_message`, `/setup_oidc`, `/setup_advanced`, `/delete_old_gift_ideas`, `/change_delete_days`, `/rundl` (purges ideas older than `DELETE_DAYS`; meant to be hit by an external cron).
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
- `tests/conftest.py` builds a temporary `DATA_DIR` per test (`.env`, `users.json`, `ideas.json` with an admin, two users in family Smith, one in family Jones, a family guest and a shared list), sets `DATA_DIR` and then (re)imports `app` and every module it loaded from `app/` (`config`, `storage`...), because `config.py` reads the data directory at import time. Patch names where they are used: `mailer.Client`, `og_image.requests` (fixtures `mailer_module`, `og_image_module`). The tracked `app/users.json`, `app/ideas.json` and `app/.env` are never touched.
- Helpers in `tests/smoke_helpers.py`: `login(client, username)`, `is_redirect_to(response, path)`, `flashes(client)`, `session_username(client)` and the test passwords/tokens. The `env` fixture exposes the temp files (`env.users()`, `env.user(name)`, `env.ideas()`, `env.idea(id)`, `env.update_user(...)`, `env.update_idea(...)`, `env.update_share_link(...)`, `env.set_env(key, value)`, which only affects keys read with `read_env_variable`). Flash messages and page text are in French unless the test calls `/set_language/en` first.
- Tests freeze current behavior. Confirmed bugs are kept as strict `xfail` tests (remove the marker when fixing one). Questionable behavior whose fix is not decided yet (e.g. security holes) is asserted as-is, in a test whose docstring starts with `CURRENT BEHAVIOR`; update that test when the behavior changes.
- No network: an autouse fixture makes socket connections fail; `requests.get` is mocked for `/fetch_og_image`, Mailjet keys are empty, OIDC is not configured.

There are no linters or CI configured.

## Translations (Flask-Babel)

Wrap user-facing strings with `_()` in Python (use named placeholders: `_('Pool "%(name)s"', name=x)`) and `{{ _('...') }}` in templates. After changing strings:
```bash
pybabel extract -F babel.cfg -o app/translations/messages.pot .
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
