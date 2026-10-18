"""Data directory, .env handling and first-start defaults."""
import io
import logging
import os
import tempfile
from pathlib import Path
from dotenv import load_dotenv, dotenv_values, set_key
from dotenv.parser import parse_stream


# Directory holding .env, users.json, ideas.json, budgets.json and Secret Santa files (set to /app/data in Docker)
DATA_DIR = os.getenv("DATA_DIR", os.path.dirname(os.path.abspath(__file__)))
dotenv_path = os.path.join(DATA_DIR, '.env') # Load the .env file from the data directory
load_dotenv(dotenv_path)
# python-dotenv warns about each line it cannot parse. It just did so once for this load; don't repeat
# it on every read_env_variable() call (such legacy lines are handled there, and set_env_variable()
# rewrites them).
logging.getLogger('dotenv.main').setLevel(logging.ERROR)

SUPPORTED_LANGUAGES = {'en': 'English', 'fr': 'Français', 'nl': 'Nederlands', 'sv': 'Svenska'}

def prepopulate_file(filename, data):
    """Create a data file with default content on first start (e.g. an empty Docker volume)."""
    if Path(filename).exists():
        return
    Path(filename).parent.mkdir(exist_ok=True, parents=True)
    with open(filename, 'w') as file:
        file.write(data)

prepopulate_file(Path(DATA_DIR, 'ideas.json'), """
        [
            {
                "user_id": "demo",
                "gift_idea_id": 1,
                "gift_name": "Default",
                "description": "dont delete",
                "link": "icbest.ca",
                "added_by": "demo",
                "bought_by": ""
            }
        ]""")

prepopulate_file(Path(DATA_DIR, 'users.json'), """
        [
        ]""")

prepopulate_file(Path(DATA_DIR, 'budgets.json'), """{"recipients": {}, "settlements": []}""")

prepopulate_file(dotenv_path, """
MAILJET_API_KEY=''
MAILJET_API_SECRET=''
SECRET_KEY='changethis'
SYSTEM_EMAIL=''
DELETE_DAYS='30'
OIDC_CLIENT_ID=''
OIDC_CLIENT_SECRET=''
OIDC_SERVER_METADATA_URL=''
OIDC_LOGOUT_URL=''
PRIMARY_OIDC_FIELD='email'
SECONDARY_OIDC_FIELD='preferred_username'
PRIMARY_DB_FIELD='email'
SECONDARY_DB_FIELD='username'
ENABLE_AUTO_REGISTRATION='false'
LOGIN_PAGE_MESSAGE='No account? Contact a family member to create an account!'
ENABLE_DEFAULT_LOGIN='true'
REORDERING='true'
IMGENABLED='false'
ENABLE_BUDGET='true'
""")


def read_env_variable(key, default=None):
    """Read a runtime-editable setting from DATA_DIR/.env at call time.

    The file is parsed by python-dotenv, so quoting, escapes, inline comments and duplicate keys
    (the last one wins) behave as for set_key(), which the admin pages use to write it. Variable
    expansion is disabled so that values written by set_key() read back unchanged.
    A key present with an empty value (or without '=') returns `default`; a key missing from the
    file falls back to the process environment, then to `default`."""
    try:
        with open(dotenv_path, 'r') as file:
            text = file.read()
    except FileNotFoundError:
        text = ''  # .env file doesn't exist, that's okay
    except Exception as e:
        print(f"Error reading .env file: {e}")
        text = ''

    values = dotenv_values(stream=io.StringIO(text), interpolate=False)
    if key in values:
        return values[key] or default

    # Older versions of the email settings and login message pages wrote values with unescaped
    # quotes, which python-dotenv cannot parse (it skips the line): read those lines as before
    legacy_value = _read_unparsed_line(text, key)
    if legacy_value is not None:
        return legacy_value or default

    # Fallback to system environment
    return os.getenv(key, default)


def _read_unparsed_line(text, key):
    """Value of the first `key=...` line, read with the rules of the former hand-written parser
    (outer quotes stripped, no escapes). Only used for lines python-dotenv could not parse."""
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            current_key, value = line.split('=', 1)
            if current_key.strip() == key:
                value = value.strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                    value = value[1:-1]
                return value
    return None


def set_env_variable(key, value):
    """set_key(), after removing `key=` lines python-dotenv cannot parse (older versions of the
    email settings and login message pages wrote values with unescaped quotes). set_key() would
    keep such a line and append a new one."""
    try:
        with open(dotenv_path, 'r') as file:
            text = file.read()
    except FileNotFoundError:
        text = ''
    bindings = list(parse_stream(io.StringIO(text)))
    kept = [binding.original.string for binding in bindings
            if not (binding.error and binding.original.string.split('=', 1)[0].strip() == key)]
    if len(kept) != len(bindings):
        # Write a temporary file and swap it in, like set_key(): other threads keep reading .env
        fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(os.path.abspath(dotenv_path)), prefix='.env.')
        with os.fdopen(fd, 'w') as file:
            file.write(''.join(kept))
        os.replace(tmp_path, dotenv_path)
    set_key(dotenv_path, key, value)
