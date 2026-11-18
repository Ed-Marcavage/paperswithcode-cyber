"""Small read-only pool for anonymous bounded catalog searches."""

from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.config import get_settings


@lru_cache
def catalog_sessions():
    settings = get_settings()
    engine = create_engine(settings.database_url, echo=False, hide_parameters=True,
                           pool_size=2, max_overflow=0, pool_timeout=1,
                           connect_args={"connect_timeout": 1, "options":
                               "-c default_transaction_read_only=on -c statement_timeout=1500 "
                               f"-c search_path={settings.db_search_path}"})
    return sessionmaker(bind=engine, expire_on_commit=False)
