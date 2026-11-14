"""Private assistant pool: never echo SQL parameters containing chat text."""

from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.config import get_settings
from backend.database.connection import database_pool_configuration


@lru_cache
def assistant_sessions():
    settings = get_settings()
    engine = create_engine(
        settings.database_url, echo=False, hide_parameters=True, pool_pre_ping=True,
        connect_args={"options": f"-c search_path={settings.db_search_path}"},
        **database_pool_configuration(settings),
    )
    return sessionmaker(bind=engine, expire_on_commit=False)
