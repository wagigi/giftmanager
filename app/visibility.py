"""Which users and groups a user is allowed to see."""


def get_visible_users(current_user, users):
    """Return the users whose lists (and profile pictures) current_user is allowed to see, based on groups."""
    is_guest = current_user.get('guest', False)
    visible_users = []
    
    if is_guest:
        # Handle guest user access
        access_type = current_user.get('access_type', 'family')
        
        if access_type == 'family':
            # Show users in guest's assigned groups (including guest groups)
            guest_groups = current_user.get('groups', [])
            visible_users = [
                user for user in users
                if user.get('groups') and any(group in guest_groups for group in user['groups'])
                and not user.get('guest')  # Don't show other guests
            ]
        else:  # people access
            # Show specific users assigned to guest
            access_users = current_user.get('access_users', [])
            visible_users = [
                user for user in users
                if user['username'] in access_users and not user.get('guest')
            ]
    else:
        # Regular user logic - SIMPLE VERSION
        current_user_groups = current_user.get('groups', [])
        
        # If current user has no groups, show all non-guest users
        if not current_user_groups:
            visible_users = [user for user in users if not user.get('guest')]
        else:
            # If current user has groups, show users who share groups OR have no groups
            visible_users = [
                user for user in users
                if (not user.get('groups') or any(group in current_user_groups for group in user.get('groups', [])))
                and not user.get('guest')
            ]

    return visible_users


def can_view_list(current_user, target_username, users):
    """True if current_user may see (and act on) the gift list of target_username:
    their own list, a user/shared list shown on their dashboard (get_visible_users), or a shared
    list they are a member of (even if an admin put that list in another family)."""
    if not current_user:
        return False
    if target_username == current_user['username'] and not current_user.get('guest'):
        return True
    target = next((user for user in users if user['username'] == target_username), None)
    if target and target.get('shared_list') and current_user['username'] in target.get('list_members', []):
        return True
    return any(user['username'] == target_username for user in get_visible_users(current_user, users))


def get_visible_groups(users):
    """Get all groups except guest private families"""
    all_groups = set()
    for user in users:
        for group in user.get('groups', []):
            # Exclude guest private families (they start with 'guest_')
            if not group.startswith('guest_'):
                all_groups.add(group)
    return sorted(all_groups)
