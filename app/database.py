import os
from datetime import datetime, UTC
from pathlib import Path
from sqlalchemy import create_engine, event, ForeignKey, UniqueConstraint, select, inspect
from sqlalchemy.pool import NullPool
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / '.env', encoding='utf-8-sig')

def now():
    return datetime.now(UTC).replace(tzinfo=None)

class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = 'users'
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(unique=True)
    display_name: Mapped[str]
    password_hash: Mapped[str]
    role: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(default=now)

class Fact(Base):
    __tablename__ = 'user_facts'
    __table_args__ = (UniqueConstraint('user_id', 'fact_key'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'))
    fact_key: Mapped[str]
    fact_value: Mapped[str]
    source: Mapped[str]
    source_message_id: Mapped[int | None] = mapped_column(ForeignKey('messages.id', ondelete='SET NULL'), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=now)
    updated_at: Mapped[datetime] = mapped_column(default=now, onupdate=now)

class Conversation(Base):
    __tablename__ = 'conversations'
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'))
    title: Mapped[str] = mapped_column(default='Новый подбор')
    created_at: Mapped[datetime] = mapped_column(default=now)
    updated_at: Mapped[datetime] = mapped_column(default=now, onupdate=now)

class Message(Base):
    __tablename__ = 'messages'
    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey('conversations.id', ondelete='CASCADE'))
    role: Mapped[str]
    content: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(default=now)

class Apartment(Base):
    __tablename__ = 'apartments'
    id: Mapped[str] = mapped_column(primary_key=True)
    building: Mapped[str]
    rooms: Mapped[int]
    area: Mapped[float]
    floor: Mapped[int]
    total_floors: Mapped[int]
    price: Mapped[int]
    finishing: Mapped[bool]
    delivery_year: Mapped[int]
    status: Mapped[str] = mapped_column(default='available')

class AuthSession(Base):
    __tablename__ = 'auth_sessions'
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'))
    token_hash: Mapped[str] = mapped_column(unique=True)
    expires_at: Mapped[datetime]
    created_at: Mapped[datetime] = mapped_column(default=now)

class RateWindow(Base):
    __tablename__ = 'rate_windows'
    key: Mapped[str] = mapped_column(primary_key=True)
    window_start: Mapped[int]
    count: Mapped[int]

class UserLease(Base):
    __tablename__ = 'user_leases'
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), primary_key=True)
    token: Mapped[str]
    expires_at: Mapped[datetime]

class EnvironmentIdentity(Base):
    __tablename__ = 'environment_identity'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]

def environment():
    platform = os.getenv('VERCEL_ENV')
    configured = os.getenv('APP_ENV')
    if platform in ('preview', 'production') and configured and configured != platform:
        raise RuntimeError('APP_ENV не совпадает с VERCEL_ENV')
    value = platform if platform in ('preview', 'production') else configured or 'development'
    if value not in ('development', 'preview', 'production', 'test'):
        raise RuntimeError('Недопустимое APP_ENV')
    return value

def make_engine(url=None):
    url = url or os.getenv('DATABASE_URL')
    env = environment()
    if not url:
        if env in ('preview', 'production'):
            raise RuntimeError('DATABASE_URL обязателен для облачной среды')
        url = 'sqlite:///' + (ROOT / 'data' / 'apartments.db').as_posix()
    if url.startswith('postgres://'):
        url = 'postgresql+psycopg://' + url[len('postgres://'):]
    elif url.startswith('postgresql://'):
        url = 'postgresql+psycopg://' + url[len('postgresql://'):]
    if url.startswith('sqlite:///'):
        if env in ('preview', 'production'):
            raise RuntimeError('Для облачной среды требуется PostgreSQL')
        if ':memory:' not in url:
            Path(url.removeprefix('sqlite:///')).parent.mkdir(parents=True, exist_ok=True)
        engine = create_engine(url, connect_args={'check_same_thread': False, 'timeout': 20})
        @event.listens_for(engine, 'connect')
        def sqlite_config(connection, _):
            connection.execute('PRAGMA foreign_keys=ON')
            connection.execute('PRAGMA journal_mode=WAL')
        return engine
    if not url.startswith('postgresql+psycopg://'):
        raise RuntimeError('Поддерживаются только SQLite и PostgreSQL с psycopg')
    sslmode = os.getenv('DB_SSL_MODE', 'require')
    if sslmode not in ('require', 'verify-full', 'disable') or (sslmode == 'disable' and env not in ('development','test')):
        raise RuntimeError('Недопустимый режим SSL для PostgreSQL')
    return create_engine(url, poolclass=NullPool, connect_args={'sslmode': sslmode, 'prepare_threshold': None})

def check_environment(engine):
    if not inspect(engine).has_table('environment_identity'):
        raise RuntimeError('База не инициализирована: выполните python -m app.setup init')
    with sessionmaker(engine)() as db:
        marker = db.get(EnvironmentIdentity, 1)
        if marker is None or marker.name != environment():
            raise RuntimeError('База не инициализирована для этого окружения')

def initialize(engine):
    inspector = inspect(engine)
    if environment() in ('preview', 'production') and not inspector.has_table('environment_identity') and any(inspector.has_table(name) for name in ('users', 'user_facts', 'conversations', 'messages', 'apartments')):
        raise RuntimeError('В базе уже есть таблицы приложения без маркера окружения; автоматическое присоединение запрещено.')
    if inspector.has_table('environment_identity'):
        with sessionmaker(engine)() as db:
            marker = db.get(EnvironmentIdentity, 1)
            if marker and marker.name != environment():
                raise RuntimeError('База принадлежит другому окружению: ' + marker.name)
    Base.metadata.create_all(engine)
    with sessionmaker(engine)() as db:
        marker = db.get(EnvironmentIdentity, 1)
        env = environment()
        if marker and marker.name != env:
            raise RuntimeError('База принадлежит другому окружению: ' + marker.name)
        if not marker:
            db.add(EnvironmentIdentity(id=1, name=env))
        db.commit()
    with sessionmaker(engine)() as db:
        rows = [
            ('A-101',1,38.2,1,12,5500000,True),('A-406',1,39.5,4,12,5900000,False),
            ('A-905',1,41.0,9,12,6400000,False),('B-203',2,58.0,2,16,8100000,True),
            ('B-705',2,61.0,7,16,8700000,True),('B-1201',2,60.0,12,16,8800000,False),
            ('C-804',2,64.0,8,16,9400000,True),('C-1104',3,74.0,11,16,10200000,True),
            ('C-301',3,78.0,3,16,10800000,False),('C-1403',3,82.0,14,16,11700000,True),
            ('A-1203',0,27.0,12,12,4300000,True),('B-102',2,56.0,1,16,7800000,True),
        ]
        for aid, rooms, area, floor, total, price, finishing in rows:
            if not db.get(Apartment, aid):
                db.add(Apartment(id=aid, building='Корпус ' + aid[0], rooms=rooms, area=area,
                    floor=floor, total_floors=total, price=price, finishing=finishing,
                    delivery_year=2028 if aid.startswith('C') else 2027))
        db.commit()
