"""
Manages connected Gmail accounts.

Accounts are persisted in data/accounts.json as a list of email strings.
Each account has its own OAuth token file at data/token_{email}.json.
The legacy token.json (first/only account) is treated as the default if no
accounts.json exists yet, providing backwards compatibility.
"""
import json
import os
import logging

logger = logging.getLogger(__name__)

DATA_DIR = "data"
ACCOUNTS_FILE = os.path.join(DATA_DIR, "accounts.json")
LEGACY_TOKEN = "token.json"


def _token_path(email: str) -> str:
    safe = email.replace("@", "_at_").replace(".", "_")
    return os.path.join(DATA_DIR, f"token_{safe}.json")


def list_accounts() -> list[str]:
    """Return list of connected account emails."""
    os.makedirs(DATA_DIR, exist_ok=True)
    if os.path.exists(ACCOUNTS_FILE):
        with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    # Backwards-compat: if legacy token.json exists, treat it as a connected account
    if os.path.exists(LEGACY_TOKEN):
        return ["__legacy__"]
    return []


def save_accounts(accounts: list[str]) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(ACCOUNTS_FILE, "w", encoding="utf-8") as f:
        json.dump(accounts, f, indent=2)


def add_account(email: str, token_json: str) -> None:
    """Persist a new account token and add the email to the accounts list."""
    os.makedirs(DATA_DIR, exist_ok=True)
    # Save token to per-account file
    with open(_token_path(email), "w", encoding="utf-8") as f:
        f.write(token_json)
    accounts = list_accounts()
    # Remove __legacy__ placeholder if present
    accounts = [a for a in accounts if a != "__legacy__"]
    if email not in accounts:
        accounts.append(email)
    save_accounts(accounts)
    logger.info("Account %s connected and token saved.", email)


def remove_account(email: str) -> bool:
    """Remove an account and delete its token. Returns True if it existed."""
    accounts = list_accounts()
    if email not in accounts:
        return False
    accounts = [a for a in accounts if a != email]
    save_accounts(accounts)
    token = _token_path(email)
    if os.path.exists(token):
        os.remove(token)
    logger.info("Account %s disconnected.", email)
    return True


def get_token_path(email: str) -> str:
    """Return the token file path for a given email (or legacy path)."""
    if email == "__legacy__":
        return LEGACY_TOKEN
    return _token_path(email)


def is_legacy_mode() -> bool:
    """True if the app is still using the old single-account token.json."""
    accounts = list_accounts()
    return accounts == ["__legacy__"] or (not accounts and os.path.exists(LEGACY_TOKEN))
