"""Give or take away admin access:  python -m admin_api.make_admin you@example.com [--remove]"""
import sys

from sqlalchemy import select

from app.db import SessionLocal
from app.models import User


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    remove = "--remove" in sys.argv
    if len(args) != 1:
        print(__doc__)
        return 2
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == args[0].lower()))
        if user is None:
            print(f"No account with email {args[0]}. Register it on the main site first.")
            return 1
        user.is_admin = not remove
        db.commit()
    print(f"{args[0]} is {'no longer' if remove else 'now'} an admin.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
