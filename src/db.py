"""PostgreSQL connection built from credentials in the local .env file."""

import os
from functools import lru_cache

from dotenv import load_dotenv
from sqlalchemy import URL, Engine, create_engine, text


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """Create the SQLAlchemy engine once and reuse it.

    Credentials are read from environment variables (DB_USER, DB_PASSWORD,
    DB_HOST, DB_PORT, DB_NAME), loaded from .env so they never appear in code.

    Returns:
        A SQLAlchemy engine connected to the project database.
    """
    load_dotenv()
    url = URL.create(
        drivername="postgresql+psycopg2",
        username=os.environ["DB_USER"],
        password=os.environ.get("DB_PASSWORD"),
        host=os.environ.get("DB_HOST", "localhost"),
        port=int(os.environ.get("DB_PORT", 5432)),
        database=os.environ["DB_NAME"],
    )
    return create_engine(url)


def check_connection() -> str:
    """Return the PostgreSQL server version to confirm the connection works."""
    with get_engine().connect() as conn:
        return conn.execute(text("SELECT version();")).scalar_one()


if __name__ == "__main__":
    print(check_connection())
