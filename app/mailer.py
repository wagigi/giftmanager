"""Outgoing email through Mailjet (optional: disabled when the API keys are unset)."""
from mailjet_rest import Client
from flask_babel import _
from config import read_env_variable
from storage import load_gift_ideas, get_user_email_by_username


def get_mailjet_client():
    """Return a Mailjet client, or None if the API keys are not configured.
    Read at call time so keys saved from the email settings page apply without restart."""
    api_key = read_env_variable("MAILJET_API_KEY")
    api_secret = read_env_variable("MAILJET_API_SECRET")
    if not api_key or not api_secret:
        return None
    return Client(auth=(api_key, api_secret), version='v3.1')


def send_email_to_buyer_via_mailjet(buyer_username, idea_name, message_subject):
    # Find the idea bought by the buyer
    gift_ideas_data = load_gift_ideas()
    for idea in gift_ideas_data:
        if idea.get('bought_by') == buyer_username:
            buyer_email = get_user_email_by_username(buyer_username)
            mailjet = get_mailjet_client()

            if not mailjet:
                print('Mailjet API keys not configured, email not sent')
            elif buyer_email:
                text_part = _("This idea, '%(name)s', has been deleted but you already BOUGHT IT.", name=idea_name)

                # Send an email to the buyer using Mailjet
                data = {
                    'Messages': [
                        {
                            'From': {
                                'Email': read_env_variable("SYSTEM_EMAIL"),  # Your sender email address
                                'Name': _('GiftManager'),
                            },
                            'To': [
                                {
                                    'Email': buyer_email,  # Buyer's email
                                    'Name': _('Buyer Name'),
                                },
                            ],
                            'Subject': message_subject,
                            'TextPart': text_part,
                        }
                    ]
                }

                # Best effort: a Mailjet failure must not prevent the deletion that triggered the email
                try:
                    response = mailjet.send.create(data=data)
                except Exception as e:
                    print(f'Failed to send email to buyer: {e}')
                else:
                    if response.status_code == 200:
                        print('Email sent to buyer successfully')
                    else:
                        print('Failed to send email to buyer')
            else:
                print(f'Buyer email not found for username: {buyer_username}')
            break
