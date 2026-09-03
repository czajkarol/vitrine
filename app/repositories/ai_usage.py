"""How much AI has been used today.

Small on purpose. The daily cap is the one number that has to be right, and it is a
`SELECT requests` against a two-column key.

The day is the *local* date, not UTC. This is a display on someone's wall and the cap is
theirs; a limit that resets in the middle of their evening because a server on another
continent rolled over would be surprising in a way that serves nobody.
"""

import asyncio
import logging
from datetime import date

from app.providers.ai.base import TokenUsage
from app.repositories.database import Database

logger = logging.getLogger(__name__)


def today() -> str:
    return date.today().isoformat()


class AiUsageRepository:
    def __init__(self, database: Database) -> None:
        self._db = database

    def requests_today_sync(self, provider: str, day: str | None = None) -> int:
        with self._db.connect() as connection:
            row = connection.execute(
                "SELECT requests FROM ai_usage WHERE day = ? AND provider = ?",
                (day or today(), provider),
            ).fetchone()
        return int(row["requests"]) if row else 0

    async def requests_today(self, provider: str, day: str | None = None) -> int:
        return await asyncio.to_thread(self.requests_today_sync, provider, day)

    def record_sync(self, provider: str, usage: TokenUsage, day: str | None = None) -> None:
        with self._db.connect() as connection:
            connection.execute(
                "INSERT INTO ai_usage (day, provider, requests, tokens_in, tokens_out)"
                " VALUES (?, ?, 1, ?, ?)"
                " ON CONFLICT(day, provider) DO UPDATE SET"
                " requests = requests + 1,"
                " tokens_in = tokens_in + excluded.tokens_in,"
                " tokens_out = tokens_out + excluded.tokens_out",
                (day or today(), provider, usage.input_tokens, usage.output_tokens),
            )

    async def record(self, provider: str, usage: TokenUsage, day: str | None = None) -> None:
        await asyncio.to_thread(self.record_sync, provider, usage, day)

    async def totals(self, day: str | None = None) -> dict[str, dict[str, int]]:
        return await asyncio.to_thread(self.totals_sync, day)

    def totals_sync(self, day: str | None = None) -> dict[str, dict[str, int]]:
        """Everything spent on one day, by provider. Read by /api/stats."""
        with self._db.connect() as connection:
            rows = connection.execute(
                "SELECT provider, requests, tokens_in, tokens_out FROM ai_usage WHERE day = ?",
                (day or today(),),
            ).fetchall()
        return {
            row["provider"]: {
                "requests": row["requests"],
                "tokens_in": row["tokens_in"],
                "tokens_out": row["tokens_out"],
            }
            for row in rows
        }
