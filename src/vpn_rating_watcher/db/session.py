from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from vpn_rating_watcher.core.settings import get_settings


def get_engine(database_url: str | None = None) -> Engine:
    if database_url is None:
        database_url = get_settings().database_url
    return create_engine(database_url, future=True, pool_pre_ping=True)


def get_session_factory(database_url: str | None = None) -> sessionmaker[Session]:
    engine = get_engine(database_url=database_url)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

