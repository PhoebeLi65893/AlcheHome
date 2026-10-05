from alembic import context

from app.db import get_engine

config = context.config


def run_migrations_online() -> None:
    with get_engine().connect() as connection:
        context.configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
