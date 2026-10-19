"""Purge of old gift ideas (admin page and /rundl)."""
from datetime import datetime, timedelta
from pathlib import Path
from flask import current_app
from config import read_env_variable
from storage import load_gift_ideas, save_gift_ideas, load_budgets, save_budgets
from budget import detach_ideas


DEFAULT_DELETE_DAYS = 30  # same default as the .env written by prepopulate_file()
MAX_DELETE_DAYS = 36500  # 100 years; much larger values overflow datetime arithmetic


def parse_delete_days(value):
    """A number of days as an int between 1 and MAX_DELETE_DAYS, or None if value is not one."""
    try:
        days = int(value)
    except (TypeError, ValueError):
        return None
    return days if 1 <= days <= MAX_DELETE_DAYS else None


def get_delete_days():
    """DELETE_DAYS from .env (days after purchase before /rundl purges an idea).
    Falls back to the default when the value is missing, empty or not an integer between 1 and
    MAX_DELETE_DAYS."""
    value = read_env_variable("DELETE_DAYS", str(DEFAULT_DELETE_DAYS))
    days = parse_delete_days(value)
    if days is not None:
        return days
    print(f"Invalid DELETE_DAYS value {value!r}, using {DEFAULT_DELETE_DAYS}")
    return DEFAULT_DELETE_DAYS


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
            if not date_str:
                continue
            try:
                idea_date = datetime.strptime(date_str, '%Y-%m-%d %H:%M:%S')
            except (TypeError, ValueError):
                # One malformed entry must not stop the purge of the others: skip it
                print(f"Skipping gift idea {idea.get('gift_idea_id')!r}: unexpected date {date_str!r}")
                continue
            if idea_date >= threshold_time:
                continue

        matches.append(idea)
    return matches

def delete_gift_ideas(bought_only, older_than_days):
    gift_ideas_data = load_gift_ideas()

    ids_to_delete = {idea['gift_idea_id'] for idea in find_gift_ideas_to_delete(gift_ideas_data, bought_only, older_than_days)}
    save_gift_ideas([idea for idea in gift_ideas_data if idea['gift_idea_id'] not in ids_to_delete])

    # Prices paid stay in the cost sharing, no longer tied to the ids (new ideas may reuse them)
    budgets = load_budgets()
    if detach_ideas(budgets, ids_to_delete):
        save_budgets(budgets)

    # Record the last execution time
    last_execution_time = datetime.now().isoformat()
    with open(Path(current_app.config['DATA'], 'last_execution_time.txt'), 'w') as time_file:
        time_file.write(last_execution_time)

    return len(ids_to_delete)

def delete_old_gift_ideas():
    # Read the number of days from the environment variable
    threshold_days = get_delete_days()

    try:
        return delete_gift_ideas(bought_only=True, older_than_days=threshold_days)
    except Exception as e:
        print(f"Error: {e}")
        return 0  # Return 0 if an error occurs
