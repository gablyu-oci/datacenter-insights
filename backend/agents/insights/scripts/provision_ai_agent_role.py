"""Provision the read-only `ai_agent` Postgres role.

Reads the SUPERUSER DSN from `SUPERUSER_DATABASE_URL` (or falls back to
`DATABASE_URL`). If `AI_AGENT_DB_PASSWORD` is not set, generates a strong
random password and prints the resulting `AI_AGENT_DB_URL` to stdout (so it
can be captured into the env file).

Usage:
    python -m backend.agents.insights.scripts.provision_ai_agent_role

Re-running is safe: the role is created if missing, or its password rotated
if already present.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import secrets
import sys
from pathlib import Path
from urllib.parse import quote, urlparse, urlunparse

import asyncpg


SQL_PATH = Path(__file__).with_name("provision_ai_agent_role.sql")
PGVECTOR_SQL = Path(__file__).with_name("enable_pgvector.sql")


def _load_sql_template(path: Path) -> str:
    """Load a psql-flavoured SQL file and lift it to a plain SQL string.

    psql's `:"name"` and `:'name'` substitution markers do not work in
    asyncpg. We pre-process the file to inline literal substitutions safely.
    """
    return path.read_text()


def _render_template(template: str, *, password: str, dbname: str) -> str:
    # Quote password for SQL string literal embedding.
    safe_pw = password.replace("'", "''")
    safe_db = dbname.replace('"', '""')
    out = template.replace(":'pw'", f"'{safe_pw}'")
    out = out.replace(':"dbname"', f'"{safe_db}"')
    return out


def _build_agent_dsn(superuser_dsn: str, password: str) -> str:
    """Build the `ai_agent` DSN by swapping user+password into the existing DSN."""
    parsed = urlparse(superuser_dsn)
    # asyncpg/sqlalchemy DSNs may be like "postgresql+asyncpg://user:pw@host:port/dbname"
    netloc_host = parsed.hostname or "localhost"
    netloc_port = f":{parsed.port}" if parsed.port else ""
    new_netloc = f"ai_agent:{quote(password)}@{netloc_host}{netloc_port}"
    new = parsed._replace(netloc=new_netloc)
    return urlunparse(new)


async def _run(superuser_dsn: str, password: str, dbname: str) -> None:
    # asyncpg expects plain "postgresql://" — strip any sqlalchemy "+driver" suffix.
    raw_dsn = superuser_dsn
    if raw_dsn.startswith("postgresql+asyncpg://"):
        raw_dsn = "postgresql://" + raw_dsn[len("postgresql+asyncpg://") :]

    conn = await asyncpg.connect(dsn=raw_dsn)
    try:
        # Run pgvector first.
        pgv_sql = _load_sql_template(PGVECTOR_SQL)
        await conn.execute(pgv_sql)

        role_sql = _render_template(
            _load_sql_template(SQL_PATH), password=password, dbname=dbname,
        )
        await conn.execute(role_sql)
    finally:
        await conn.close()


def _resolve_dbname(superuser_dsn: str) -> str:
    parsed = urlparse(superuser_dsn)
    # Path is "/dbname"
    return (parsed.path or "/").lstrip("/") or "postgres"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--superuser-dsn",
        default=os.environ.get("SUPERUSER_DATABASE_URL")
        or os.environ.get("DATABASE_URL"),
        help="Postgres superuser DSN (default: env SUPERUSER_DATABASE_URL or DATABASE_URL)",
    )
    parser.add_argument(
        "--password",
        default=os.environ.get("AI_AGENT_DB_PASSWORD"),
        help="Password for the ai_agent role (default: env AI_AGENT_DB_PASSWORD; random if unset)",
    )
    args = parser.parse_args(argv)

    if not args.superuser_dsn:
        print(
            "ERROR: must provide --superuser-dsn or set SUPERUSER_DATABASE_URL/DATABASE_URL",
            file=sys.stderr,
        )
        return 2

    pw = args.password or secrets.token_urlsafe(32)
    dbname = _resolve_dbname(args.superuser_dsn)

    asyncio.run(_run(args.superuser_dsn, pw, dbname))

    agent_dsn = _build_agent_dsn(args.superuser_dsn, pw)
    print("ai_agent role provisioned successfully.", file=sys.stderr)
    print(f"AI_AGENT_DB_URL={agent_dsn}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
