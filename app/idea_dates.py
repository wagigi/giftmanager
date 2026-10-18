"""Dates on gift ideas: startup backfill of missing dates and the age shown next to each idea."""
import json
from datetime import datetime
from pathlib import Path
from flask_babel import _, ngettext


DATE_FORMAT = '%Y-%m-%d %H:%M:%S'  # format of date_added and date_bought


def backfill_missing_dates(ideas, now=None):
    """Give the current date to ideas without date_added, and to bought ideas without date_bought
    (bought with older versions of the app, they were never purged by /rundl), flagging each such date
    with date_added_unknown / date_bought_unknown. Changes `ideas` in place and returns how many changed."""
    stamp = (now or datetime.now()).strftime(DATE_FORMAT)
    changed = 0
    for idea in ideas:
        touched = False
        if not idea.get('date_added'):
            idea['date_added'] = stamp
            idea['date_added_unknown'] = True
            touched = True
        if idea.get('bought_by') and not idea.get('date_bought'):
            idea['date_bought'] = stamp
            idea['date_bought_unknown'] = True
            touched = True
        changed += touched
    return changed


def migrate_ideas_file(ideas_path):
    """Run backfill_missing_dates() on the ideas file at startup, rewriting it only when a date was missing."""
    path = Path(ideas_path)
    try:
        with open(path, 'r') as file:
            ideas = json.load(file)
    except (OSError, ValueError) as e:
        print(f"Could not check the dates of the gift ideas in {path}: {e}")
        return 0

    changed = backfill_missing_dates(ideas)
    if changed:
        with open(path, 'w') as file:
            json.dump(ideas, file, indent=4)  # same format as save_gift_ideas()
        print(f"Added missing dates to {changed} gift ideas")
    return changed


def idea_age(idea, today=None):
    """Age of an idea since it was added, as {'label': ..., 'unknown': ...}, or None without a readable
    date_added. `unknown` is set for dates filled in by backfill_missing_dates(): the idea is at least
    that old, and the label says so ("More than 3 days")."""
    try:
        added = datetime.strptime(idea.get('date_added') or '', DATE_FORMAT).date()
    except (TypeError, ValueError):
        return None
    today = today or datetime.now().date()
    unknown = bool(idea.get('date_added_unknown'))

    days = max((today - added).days, 0)
    months = max((today.year - added.year) * 12 + today.month - added.month - (today.day < added.day), 0)

    if days == 0:
        label = _('Date unknown') if unknown else _('Today')
    elif months < 1:
        label = (ngettext('More than %(num)d day', 'More than %(num)d days', days) if unknown
                 else ngettext('%(num)d day', '%(num)d days', days))
    elif months < 12:
        label = (ngettext('More than %(num)d month', 'More than %(num)d months', months) if unknown
                 else ngettext('%(num)d month', '%(num)d months', months))
    else:
        years = months // 12
        label = (ngettext('More than %(num)d year', 'More than %(num)d years', years) if unknown
                 else ngettext('%(num)d year', '%(num)d years', years))
    return {'label': label, 'unknown': unknown}
