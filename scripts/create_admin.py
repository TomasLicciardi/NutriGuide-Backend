"""Crea un usuario administrador o promueve uno existente a admin.

Uso:
    python scripts/create_admin.py --email admin@nutriguide.local --password secret123 --username admin

Si el usuario ya existe, lo promueve a is_admin=True sin tocar password.
Si no existe, lo crea con esa contraseña.
"""

import argparse
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.database.connection import init_database, get_db
from app.models.user import User
from app.utils.security import hash_password


def main() -> int:
    parser = argparse.ArgumentParser(description="Crear o promover usuario admin")
    parser.add_argument("--email", required=True, help="Email del usuario")
    parser.add_argument("--password", required=True, help="Password (solo si se crea)")
    parser.add_argument("--username", default="admin", help="Username (default: admin)")
    args = parser.parse_args()

    init_database()
    db = next(get_db())
    try:
        existing = db.query(User).filter(User.email == args.email).first()
        if existing:
            if existing.is_admin:
                print(f"✓ {args.email} ya era admin (id={existing.id})")
            else:
                existing.is_admin = True
                db.commit()
                print(f"✓ {args.email} promovido a admin (id={existing.id})")
            return 0

        new_user = User(
            username=args.username,
            email=args.email,
            password=hash_password(args.password),
            restrictions="[]",
            is_admin=True,
        )
        db.add(new_user)
        db.commit()
        db.refresh(new_user)
        print(f"✓ Admin creado: id={new_user.id}, email={new_user.email}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
