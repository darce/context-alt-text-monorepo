from __future__ import annotations

import logging
import os
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

from db import session as db_session
from db.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

logger = logging.getLogger("alembic.env")

target_metadata = Base.metadata

# Import custom types for type comparison
from db.models import JSONType, UUIDType, VectorType

def render_uuid_type(type_, obj, autogen_context):
    """Render UUIDType for migrations as PostgreSQL UUID."""
    # In migrations, render as sa.dialects.postgresql.UUID instead of UUIDType
    # This way the migration is explicit about using PostgreSQL's native UUID type
    return "sa.dialects.postgresql.UUID(as_uuid=True)"

def render_json_type(type_, obj, autogen_context):
    """Render JSONType for migrations as PostgreSQL JSONB."""
    # In migrations, render as sa.dialects.postgresql.JSONB
    return "sa.dialects.postgresql.JSONB()"

def render_vector_type(type_, obj, autogen_context):
    """Render VectorType for migrations."""
    # For VectorType, we need to use the pgvector type directly
    # Get the dimension from the VectorType instance
    dim = getattr(obj, 'dim', 512)
    return f"pgvector.sqlalchemy.Vector({dim})"


def render_item(type_, obj, autogen_context):
    """Custom renderer for our custom types."""
    if isinstance(obj, UUIDType):
        return render_uuid_type(type_, obj, autogen_context)
    elif isinstance(obj, JSONType):
        return render_json_type(type_, obj, autogen_context)
    elif isinstance(obj, VectorType):
        return render_vector_type(type_, obj, autogen_context)
    
    # Fall back to default rendering
    return False



def _load_env_file():
    """Load environment variables from .env file if it exists."""
    env_file = Path(__file__).parent.parent.parent / ".env"
    if env_file.exists():
        logger.info(f"Loading environment from {env_file}")
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                # Skip comments and empty lines
                if not line or line.startswith("#"):
                    continue
                # Parse KEY=VALUE
                if "=" in line:
                    key, value = line.split("=", 1)
                    key = key.strip()
                    value = value.strip()
                    # Only set if not already in environment
                    if key not in os.environ:
                        os.environ[key] = value


def _get_database_url() -> str:
    """Get database URL from environment or use SQLite default for local dev."""
    # Load .env file first
    _load_env_file()
    
    override = os.getenv("DATABASE_URL")
    if override:
        return override
    
    # Check if there's a URL in alembic.ini
    config_url = config.get_main_option("sqlalchemy.url")
    if config_url:
        return config_url
    
    # Default to SQLite for local development
    default_sqlite = "sqlite:///./data/recognition.db"
    logger.warning(
        f"DATABASE_URL not set, using default SQLite: {default_sqlite}. "
        "Set DATABASE_URL environment variable for production databases."
    )
    return default_sqlite


def run_migrations_offline() -> None:
    url = _get_database_url()
    
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_item=render_item,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = _get_database_url()

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, 
            target_metadata=target_metadata,
            render_item=render_item,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
