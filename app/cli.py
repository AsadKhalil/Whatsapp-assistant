"""Server commands for the dashboard.

  python -m app.cli create-admin EMAIL   create an admin login and print its invite link
  python -m app.cli admin-link EMAIL     print a fresh link for a locked-out admin (resets password and two-step)
"""
from __future__ import annotations

import sys

from app.auth import Auth, AuthError
from app.config import Settings
from app.db import Db
from app.registry import Registry
from app.vault import Vault


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2 or args[0] not in ("create-admin", "admin-link"):
        print(__doc__)
        return 2
    settings = Settings.from_env()
    if not settings.secret_key:
        print("Set SECRET_KEY in .env first (make one with: openssl rand -hex 32).")
        return 1
    db, vault = Db(settings.db_path), Vault(settings.secret_key)
    Registry(db, vault)  # creates the businesses table that logins refer to
    auth = Auth(db, vault)
    command, email = args
    try:
        if command == "create-admin":
            token = auth.invite(email, "", "admin", None)
        else:
            user = auth.by_email(email)
            if user is None or user.role != "admin":
                print(f"No admin login for {email}.")
                return 1
            token = auth.new_link(user.id, reset_totp=True)
    except AuthError as e:
        print(e)
        return 1
    print(f"{settings.public_url.rstrip('/') or 'https://<your-domain>'}/invite/{token}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
