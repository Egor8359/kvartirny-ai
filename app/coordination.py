import hashlib, secrets, time
from datetime import timedelta
from sqlalchemy import delete
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.dialects.postgresql import insert as pg_insert
from .database import RateWindow, UserLease, now

def insert_for(engine, table):
    return (sqlite_insert if engine.dialect.name == 'sqlite' else pg_insert)(table)

def consume(engine, name, identity, limit, seconds):
    stamp = int(time.time())
    bucket = stamp // seconds * seconds
    key = f"{name}:{hashlib.sha256(identity.encode()).hexdigest()}:{bucket}"
    statement = insert_for(engine, RateWindow).values(key=key, window_start=bucket, count=1)
    statement = statement.on_conflict_do_update(index_elements=[RateWindow.key], set_={'count': RateWindow.count + 1}).returning(RateWindow.count)
    with engine.begin() as connection:
        connection.execute(delete(RateWindow).where(RateWindow.window_start < stamp - 86400))
        return connection.execute(statement).scalar_one() <= limit

def acquire(engine, user_id):
    token = secrets.token_urlsafe(24)
    current = now()
    statement = insert_for(engine, UserLease).values(user_id=user_id, token=token, expires_at=current + timedelta(minutes=10))
    statement = statement.on_conflict_do_update(index_elements=[UserLease.user_id], set_={'token': token, 'expires_at':current + timedelta(minutes=10)}, where=UserLease.expires_at < current).returning(UserLease.token)
    with engine.begin() as connection:
        return connection.execute(statement).scalar_one_or_none()

def release(engine, user_id, token):
    with engine.begin() as connection:
        connection.execute(delete(UserLease).where(UserLease.user_id == user_id, UserLease.token == token))
