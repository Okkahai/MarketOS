import os

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine

DB_URL = os.environ.get("TEST_DATABASE_URL")
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))


def alembic_config() -> Config:
    cfg = Config(os.path.join(BACKEND_DIR, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(BACKEND_DIR, "alembic"))
    cfg.set_main_option("sqlalchemy.url", DB_URL)
    return cfg


@pytest.fixture
def migrated():
    """A freshly migrated database, dropped again afterwards."""
    cfg = alembic_config()
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    engine = create_engine(DB_URL)
    yield engine
    engine.dispose()
    command.downgrade(cfg, "base")
