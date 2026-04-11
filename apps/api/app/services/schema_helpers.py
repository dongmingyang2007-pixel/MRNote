from __future__ import annotations

from sqlalchemy import inspect, text as sql_text
from sqlalchemy.engine import Engine


def ensure_column(
    engine: Engine,
    table: str,
    column: str,
    column_type: str,
    *,
    nullable: bool = True,
    default: str | None = None,
) -> None:
    """Add a column to a table if it doesn't exist."""
    inspector = inspect(engine)
    if table not in set(inspector.get_table_names()):
        return
    columns = {c["name"] for c in inspector.get_columns(table)}
    if column in columns:
        return

    sql = f"ALTER TABLE {table} ADD COLUMN {column} {column_type}"
    if not nullable:
        sql += " NOT NULL"
    if default is not None:
        sql += f" DEFAULT {default}"

    with engine.begin() as conn:
        conn.execute(sql_text(sql))
