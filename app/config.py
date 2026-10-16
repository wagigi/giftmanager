"""Data directory, .env handling and first-start defaults."""
import os
from pathlib import Path
from dotenv import load_dotenv


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
    """Read environment variable from .env file with proper defaults"""
    # Define the path here to avoid the default parameter issue
    env_path = dotenv_path
    
    try:
        with open(env_path, 'r') as file:
            for line in file:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    current_key, value = line.split('=', 1)
                    if current_key.strip() == key:
                        value = value.strip()
                        # Remove quotes
                        if value and ((value[0] == '"' and value[-1] == '"') or (value[0] == "'" and value[-1] == "'")):
                            value = value[1:-1]
                        return value if value else default
    except FileNotFoundError:
        pass  # .env file doesn't exist, that's okay
    except Exception as e:
        print(f"Error reading .env file: {e}")
    
    # Fallback to system environment
    return os.getenv(key, default)
