import os
import psycopg2
from psycopg2.extras import RealDictCursor
from pgvector.psycopg2 import register_vector

DSN = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5433/contextbridge")


def init_schema():
    """Destructive: drops and recreates all tables."""
    conn = psycopg2.connect(DSN)
    with conn, conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
        cur.execute("DROP TABLE IF EXISTS tasks, transfers, chunks, documents, users CASCADE")
        cur.execute(open(os.path.join(os.path.dirname(__file__), "schema.sql")).read())
    conn.close()


def query(sql, params=()):
    conn = psycopg2.connect(DSN)
    register_vector(conn)
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall() if cur.description else []
        conn.commit()
        return rows
    finally:
        conn.close()
