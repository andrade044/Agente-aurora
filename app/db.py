"""Acesso ao PostgreSQL via pool de conexões (psycopg 3)."""
from __future__ import annotations

import time
from typing import Any, Iterable

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.config import settings

_pool: ConnectionPool | None = None


def init_pool(retries: int = 30, delay_s: float = 2.0) -> ConnectionPool:
    """Abre o pool, aguardando o banco ficar disponível (útil no docker compose)."""
    global _pool
    if _pool is not None:
        return _pool
    last_error: Exception | None = None
    for _ in range(retries):
        try:
            pool = ConnectionPool(
                settings.database_url,
                min_size=1,
                max_size=5,
                kwargs={"row_factory": dict_row},
                open=True,
                timeout=5,
            )
            with pool.connection() as conn:
                conn.execute("SELECT 1")
            _pool = pool
            return pool
        except Exception as exc:  # noqa: BLE001 - queremos repetir em qualquer falha de conexão
            last_error = exc
            time.sleep(delay_s)
    raise RuntimeError(f"Não foi possível conectar ao banco: {last_error}")


def get_pool() -> ConnectionPool:
    return _pool if _pool is not None else init_pool()


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


def fetch_all(sql: str, params: Iterable[Any] | dict | None = None) -> list[dict]:
    with get_pool().connection() as conn:
        return conn.execute(sql, params).fetchall()


def fetch_one(sql: str, params: Iterable[Any] | dict | None = None) -> dict | None:
    with get_pool().connection() as conn:
        return conn.execute(sql, params).fetchone()


def execute(sql: str, params: Iterable[Any] | dict | None = None) -> None:
    with get_pool().connection() as conn:
        conn.execute(sql, params)
