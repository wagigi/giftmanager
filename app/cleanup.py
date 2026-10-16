"""Purge of old gift ideas (admin page and /rundl)."""
from datetime import datetime, timedelta
from pathlib import Path
from flask import current_app
from config import dotenv_path, read_env_variable
from storage import load_gift_ideas, save_gift_ideas


def find_gift_ideas_to_delete(gift_ideas_data, bought_only, older_than_days):
    threshold_time = datetime.now() - timedelta(days=older_than_days) if older_than_days else None

    matches = []
    for idea in gift_ideas_data:
        if bought_only and not idea.get('bought_by'):
            continue

        if threshold_time:
            # Age counts from the purchase date for bought ideas, otherwise from when the idea was added.
            # Ideas without a known date are never considered old.
            date_str = idea.get('date_bought') if idea.get('bought_by') else idea.get('date_added')
            if not date_str or datetime.strptime(date_str, '%Y-%m-%d %H:%M:%S') >= threshold_time:
                continue

        matches.append(idea)
    return matches

def delete_gift_ideas(bought_only, older_than_days):
    gift_ideas_data = load_gift_ideas()

    ids_to_delete = {idea['gift_idea_id'] for idea in find_gift_ideas_to_delete(gift_ideas_data, bought_only, older_than_days)}
    save_gift_ideas([idea for idea in gift_ideas_data if idea['gift_idea_id'] not in ids_to_delete])

    # Record the last execution time
    last_execution_time = datetime.now().isoformat()
    with open(Path(current_app.config['DATA'], 'last_execution_time.txt'), 'w') as time_file:
        time_file.write(last_execution_time)

    return len(ids_to_delete)

def delete_old_gift_ideas():
    # Read the number of days from the environment variable
    threshold_days = int(read_env_variable("DELETE_DAYS", dotenv_path) or 30)

    try:
        return delete_gift_ideas(bought_only=True, older_than_days=threshold_days)
    except Exception as e:
        print(f"Error: {e}")
        return 0  # Return 0 if an error occurs
