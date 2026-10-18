"""Flat JSON storage: users.json, ideas.json and budgets.json, read and rewritten in full."""
import json
from flask import current_app


def load_gift_ideas():
    with open(current_app.config['IDEAS_FILE'], 'r') as file:
        return json.load(file)

def save_gift_ideas(gift_ideas):
    with open(current_app.config['IDEAS_FILE'], 'w') as file:
        json.dump(gift_ideas, file, indent=4)

def load_budgets():
    with open(current_app.config['BUDGETS_FILE'], 'r') as file:
        budgets = json.load(file)
    budgets.setdefault('recipients', {})
    budgets.setdefault('settlements', [])
    return budgets

def save_budgets(budgets):
    with open(current_app.config['BUDGETS_FILE'], 'w') as file:
        json.dump(budgets, file, indent=4)

def load_users():
    with open(current_app.config['USERS_FILE'], 'r') as file:
        return json.load(file)

def save_users(users):
    with open(current_app.config['USERS_FILE'], 'w') as file:
        json.dump(users, file, indent=4)


def get_user_email_by_username(username):
    # Use the helper function to load users
    users = load_users()

    # Find the user by username
    user = next((u for u in users if u['username'] == username), None)
    return user.get('email') if user else None


def find_idea_by_id(ideas, idea_id):
    # Iterate through the list of ideas
    for idea in ideas:
        # If the gift_idea_id matches, return the idea
        if idea['gift_idea_id'] == idea_id:
            return idea
    # Return None if no matching idea is found
    return None


def get_full_name(username):
    users = load_users()  # Load the users from the JSON file
    for user in users:
        if user['username'] == username:
            return user.get('full_name') or username  # Return the full name or fallback to username
    return username  # If no match found, return the username itself
