from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context
from app.models import Base
from app.config import get_settings

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

settings = get_settings()

# Derive a sync URL: prefer SYNC_DATABASE_URL, but fall back to DATABASE_URL
# converting async drivers (asyncpg / aiosqlite) to their sync equivalents.
_sync_url = settings.sync_database_url
if _sync_url.startswith("sqlite+aiosqlite"):
    # If SYNC_DATABASE_URL is still the SQLite default, use DATABASE_URL instead
    _db_url = settings.database_url
    _sync_url = (
        _db_url
        .replace("postgresql+asyncpg://", "postgresql://")
        .replace("postgresql+aiopg://", "postgresql://")
        .replace("sqlite+aiosqlite://", "sqlite://")
    )

config.set_main_option('sqlalchemy.url', _sync_url)
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(url=settings.sync_database_url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix='sqlalchemy.',
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
