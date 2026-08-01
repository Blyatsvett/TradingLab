import sqlite3
import pandas as pd

from .settings import DB_PATH


def get_connection() -> sqlite3.Connection:
    return sqlite3.connect(DB_PATH)


def write_table(df: pd.DataFrame, table_name: str, if_exists: str = "replace") -> None:
    with get_connection() as conn:
        df.to_sql(table_name, conn, if_exists=if_exists, index=False)


def read_table(table_name: str) -> pd.DataFrame:
    with get_connection() as conn:
        return pd.read_sql_query(f'SELECT * FROM "{table_name}"', conn)
