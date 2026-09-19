"""Minimal D1 helpers — prefer single-statement paths to save Free quota."""

from __future__ import annotations

from typing import Any, Optional


def _rows(result: Any) -> list[dict]:
    if result is None:
        return []
    # JS proxy objects expose .results
    rows = getattr(result, "results", None)
    if rows is None and isinstance(result, dict):
        rows = result.get("results")
    return list(rows or [])


async def one(db, sql: str, *args) -> Optional[dict]:
    stmt = db.prepare(sql)
    if args:
        stmt = stmt.bind(*args)
    result = await stmt.first()
    if result is None:
        return None
    if isinstance(result, dict):
        return result
    # Proxy row → dict
    try:
        return dict(result)
    except Exception:
        return result


async def all(db, sql: str, *args) -> list[dict]:
    stmt = db.prepare(sql)
    if args:
        stmt = stmt.bind(*args)
    result = await stmt.all()
    rows = _rows(result)
    out = []
    for r in rows:
        try:
            out.append(dict(r))
        except Exception:
            out.append(r)
    return out


async def run(db, sql: str, *args) -> Any:
    stmt = db.prepare(sql)
    if args:
        stmt = stmt.bind(*args)
    return await stmt.run()


async def batch(db, statements: list) -> Any:
    """statements: list of prepared bound statements."""
    return await db.batch(statements)
