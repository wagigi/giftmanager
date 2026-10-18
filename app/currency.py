"""Currency display settings."""
from config import read_env_variable


def get_currency_symbol():
    return read_env_variable("CURRENCY_SYMBOL", "$")

def get_currency_position():
    return read_env_variable("CURRENCY_POSITION", "before")

def format_currency(amount):
    symbol = get_currency_symbol()
    position = get_currency_position()
    
    if position == 'after':
        return f"{amount}{symbol}"
    else:  # before (default)
        return f"{symbol}{amount}"
