import argparse

from sqlalchemy import select

from src.auth.domain.password_policy import PasswordPolicy
from src.auth.infrastructure.persistence.models.user import UserModel
from src.auth.infrastructure.security.password_hasher import PasswordHasher
from src.infrastructure.database.session import SessionLocal
from src.roles.infrastructure.persistence.models.role import RoleModel


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create the initial FashionStore superadministrator.")
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--first-name", required=True)
    parser.add_argument("--last-name", required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    email = args.email.strip().lower()
    PasswordPolicy.validate(args.password, email=email)
    with SessionLocal() as db:
        if db.scalar(select(UserModel).where(UserModel.email == email)):
            raise SystemExit("A user with that email already exists.")
        role = db.scalar(select(RoleModel).where(RoleModel.code == "superadmin"))
        if not role:
            raise SystemExit("The superadmin role does not exist. Apply the initial migration first.")
        user = UserModel(
            email=email,
            password_hash=PasswordHasher().hash(args.password),
            first_name=args.first_name.strip(),
            last_name=args.last_name.strip(),
            is_active=True,
            is_verified=True,
            roles=[role],
        )
        db.add(user)
        db.commit()
        print(f"Superadministrator created: {user.email}")


if __name__ == "__main__":
    main()
