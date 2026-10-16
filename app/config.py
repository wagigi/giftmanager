"""Data directory, .env handling and first-start defaults."""
import os
from pathlib import Path
from dotenv import load_dotenv, dotenv_values


# Directory holding .env, users.json, ideas.json and Secret Santa files (set to /app/data in Docker)
DATA_DIR = os.getenv("DATA_DIR", os.path.dirname(os.path.abspath(__file__)))
dotenv_path = os.path.join(DATA_DIR, '.env') # Load the .env file from the data directory
load_dotenv(dotenv_path)

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
""")


def read_env_variable(key, default=None):
    """Read a runtime-editable setting from DATA_DIR/.env at call time.

    The file is parsed by python-dotenv, so quoting, escapes, inline comments and duplicate keys
    (the last one wins) behave as for set_key(), which the admin pages use to write it. Variable
    expansion is disabled so that values written by set_key() read back unchanged.
    A key present with an empty value (or without '=') returns `default`; a key missing from the
    file falls back to the process environment, then to `default`."""
    try:
        values = dotenv_values(dotenv_path, interpolate=False)
    except Exception as e:
        print(f"Error reading .env file: {e}")
        values = {}

    if key in values:
        return values[key] or default

    # Fallback to system environment
    return os.getenv(key, default)
