"""
One-shot driver for the county building-permit adapters
(the user-fixes AC3).

Run from the backend dir:
    .venv/bin/python -m scripts.run_county_permits_once

Calls Loudoun + Mesa + Grant County adapters sequentially and prints
per-source counts. Use to seed the building_permits table after the
008 migration is applied.
"""
from __future__ import annotations

import asyncio
import json

from db.session import async_session_factory
from ingestion.permits_county import grantwa, loudoun, mesa


async def _main() -> None:
    print("== run_county_permits_once ==")
    summary: list[dict] = []
    for mod in (loudoun, mesa, grantwa):
        name = getattr(mod, "SOURCE_ID", mod.__name__)
        print(f"-> running {name} ...")
        async with async_session_factory() as session:
            try:
                result = await mod.fetch_and_store(session)
            except Exception as exc:  # noqa: BLE001 -- we want full visibility
                result = {"source": name, "error": str(exc)}
                print(f"   !! {name} raised: {exc}")
        print(f"   {json.dumps(result)}")
        summary.append(result)

    print("\n== summary ==")
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(_main())
