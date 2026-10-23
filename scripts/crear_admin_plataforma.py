"""Crear el administrador de plataforma, con contraseña recibida del entorno."""
import argparse
import os
from sqlalchemy import select
from src.auth.domain.password_policy import PasswordPolicy
from src.auth.infrastructure.persistence.models.user import UserModel
from src.auth.infrastructure.security.password_hasher import PasswordHasher
from src.roles.infrastructure.persistence.models.role import RoleModel

def crear(db, email, password):
    email = email.strip().lower()
    PasswordPolicy.validate(password, email=email)
    role = db.scalar(select(RoleModel).where(RoleModel.code == 'platform_admin'))
    if role is None:
        raise ValueError('Aplica primero la migración0016 en la base prevista.')
    user = db.scalar(select(UserModel).where(UserModel.email == email))
    if user is not None and (user.tenant_id is not None or not any(r.code == 'platform_admin' for r in user.roles)):
        raise ValueError('El correo ya pertenece a una cuenta de empresa; no se cambia su alcance.')
    if user is None:
        user = UserModel(email=email, first_name='Administrador', last_name='Plataforma', tenant_id=None, roles=[role])
        db.add(user)
    user.password_hash = PasswordHasher().hash(password)
    user.is_active = True
    user.is_verified = True
    user.deleted_at = None
    user.failed_login_attempts = 0
    user.locked_until = None
    if user.id is not None:
        from src.auth.infrastructure.persistence.repositories.auth_token_repository import AuthTokenRepository
        AuthTokenRepository(db).revoke_all_for_user(user.id)
    db.commit()
    return user

def main(email):
    password = os.environ.get('PLATFORM_ADMIN_PASSWORD')
    if not password:
        raise ValueError('Define PLATFORM_ADMIN_PASSWORD; nunca se imprime ni se guarda en código.')
    from src.infrastructure.database.session import SessionLocal
    with SessionLocal() as db:
        crear(db, email, password)
    print('Administrador de plataforma preparado.')

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--email', required=True)
    args = parser.parse_args()
    main(args.email)
