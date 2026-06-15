"""Alembic environment file for migrations."""
from __future__ import annotations
import os
from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Import the unified Base and ALL models so their tables register
# in Base.metadata for autogenerate to detect.
from app.models.base import Base
import app.models.persisted_course  # noqa: F401 — CourseRecord, TemplateRecord, etc.
import app.models.template_type    # noqa: F401 — TemplateType
import app.models.component_type   # noqa: F401 — ComponentType
import app.models.page_component   # noqa: F401 — PageRecord, ComponentRecord
import app.models.theme            # noqa: F401 — ThemeRecord
import app.models.scoring          # noqa: F401 — CourseScoringRecord
import app.models.branching        # noqa: F401 — BranchRule, BranchEvent
import app.models.social           # noqa: F401 — Discussion, PeerReview, Poll, Team
import app.models.interaction_event  # noqa: F401 — InteractionEventRecord
import app.models.ai_models  # noqa: F401 — AISessionRecord, AIProposalRecord, etc.

# This is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def get_database_url() -> str:
    """Get database URL from environment (matches app/db/config.py logic).
    
    Converts asyncpg URLs to psycopg2 for synchronous Alembic migrations.
    """
    if "DATABASE_URL" in os.environ:
        url = os.environ["DATABASE_URL"]
        # Convert asyncpg to psycopg2 for synchronous migrations
        if "asyncpg" in url:
            url = url.replace("postgresql+asyncpg://", "postgresql://")
        return url
    
    # Construct PostgreSQL URL from components
    pg_user = os.getenv("POSTGRES_USER", "postgres")
    pg_password = os.getenv("POSTGRES_PASSWORD", "postgres")
    pg_host = os.getenv("POSTGRES_HOST", "localhost")
    pg_port = os.getenv("POSTGRES_PORT", "5432")
    pg_db = os.getenv("POSTGRES_DB", "elearning")
    
    # Use synchronous psycopg2 for migrations (not asyncpg)
    return (
        f"postgresql://{pg_user}:{pg_password}"
        f"@{pg_host}:{pg_port}/{pg_db}"
    )


# Override DB URL from environment
DATABASE_URL = get_database_url()
if DATABASE_URL:
    config.set_main_option("sqlalchemy.url", DATABASE_URL)

target_metadata = Base.metadata

 
def run_migrations_offline():
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()

 
def run_migrations_online():
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )

        with context.begin_transaction():
            context.run_migrations()

 
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
