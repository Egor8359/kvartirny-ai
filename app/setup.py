"""Explicit, non-destructive schema/catalog initialization and account provisioning."""
import argparse
import getpass
from sqlalchemy import select
from sqlalchemy.orm import Session
from .database import User, initialize, make_engine, check_environment
from .security import hash_password


def main():
    parser = argparse.ArgumentParser(description='Управляемая настройка базы')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('init', help='Создать отсутствующие таблицы и заполнить каталог')
    user = commands.add_parser('create-user', help='Создать отдельный аккаунт')
    user.add_argument('--username', required=True)
    user.add_argument('--name', required=True)
    user.add_argument('--role', choices=['client', 'admin'], required=True)
    args = parser.parse_args()
    engine = make_engine()
    try:
        if args.command == 'init':
            initialize(engine)
            print('Схема и каталог проверены; существующие данные не изменялись.')
        else:
            check_environment(engine)
            if not (1 <= len(args.username) <= 80 and 1 <= len(args.name) <= 100):
                raise SystemExit('Недопустимое имя или логин')
            with Session(engine) as db:
                if db.scalar(select(User.id).where(User.username == args.username)):
                    raise SystemExit('Логин занят; существующая учётная запись не изменена.')
                password = getpass.getpass('Новый пароль (не менее 12 символов): ')
                if len(password) < 12 or password != getpass.getpass('Повторите пароль: '):
                    raise SystemExit('Пароль слишком короткий или не совпадает.')
                db.add(User(username=args.username, display_name=args.name, role=args.role, password_hash=hash_password(password)))
                db.commit()
            print('Аккаунт создан.')
    finally:
        engine.dispose()

if __name__ == '__main__':
    main()
