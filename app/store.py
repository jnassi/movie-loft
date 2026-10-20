"""Tag storage. Postgres when DATABASE_URL is set; an in-memory dict otherwise
(local development only — nothing persists across restarts).

One table, created on startup if missing. Small enough that a migrations tool
would be more machinery than schema; if this grows past a couple of tables,
switch to a migrations tool such as Alembic.
"""
import os

import asyncpg

DATABASE_URL = os.environ.get("DATABASE_URL", "")
_pool = None
_mem = {}          # (kind, key, tag) -> who

SCHEMA_TUNE = """
CREATE TABLE IF NOT EXISTS tune_requests (
    id           bigserial PRIMARY KEY,
    room         text NOT NULL,
    link         text NOT NULL,
    title        text NOT NULL,
    position     integer,              -- seconds into the title at requested_at; NULL = just open it
    requested_by text NOT NULL,
    requested_at timestamptz NOT NULL DEFAULT now(),
    status       text NOT NULL DEFAULT 'pending',   -- pending → claimed → working → done | failed | expired
    message      text,
    updated_at   timestamptz NOT NULL DEFAULT now()
)"""

SCHEMA = """
CREATE TABLE IF NOT EXISTS tags (
    kind       text NOT NULL,
    key        text NOT NULL,
    tag        text NOT NULL,
    added_by   text NOT NULL,
    added_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (kind, key, tag)
)"""


async def connect():
    global _pool
    if DATABASE_URL:
        _pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=4)
        async with _pool.acquire() as conn:
            await conn.execute(SCHEMA)
            await conn.execute(SCHEMA_TUNE)
            await conn.execute("ALTER TABLE tune_requests ADD COLUMN IF NOT EXISTS "
                               "from_start boolean NOT NULL DEFAULT false")
            # (the status comment above gained 'working'; no column change needed)


async def close():
    if _pool:
        await _pool.close()


async def all_tags():
    """{"comfort": {"movie": [...raw titles], "show": [...show names]}}"""
    if _pool:
        async with _pool.acquire() as conn:
            rows = await conn.fetch("SELECT kind, key, tag FROM tags ORDER BY key")
        triples = [(r["kind"], r["key"], r["tag"]) for r in rows]
    else:
        triples = sorted(_mem, key=lambda t: t[1])
    out = {}
    for kind, key, tag in triples:
        out.setdefault(tag, {"movie": [], "show": []})[kind].append(key)
    return out


async def set_tag(kind, key, tag, on, who):
    if _pool:
        async with _pool.acquire() as conn:
            if on:
                await conn.execute(
                    "INSERT INTO tags (kind, key, tag, added_by) VALUES ($1, $2, $3, $4) "
                    "ON CONFLICT DO NOTHING", kind, key, tag, who)
            else:
                await conn.execute(
                    "DELETE FROM tags WHERE kind = $1 AND key = $2 AND tag = $3", kind, key, tag)
    elif on:
        _mem[(kind, key, tag)] = who
    else:
        _mem.pop((kind, key, tag), None)


# ------------------------------------------------------------- tune requests
# The phone queues a request; the helper on the Mac claims it, drives the
# Apple TV, and reports back. In-memory fallback mirrors the table for local dev.
_tunes = {}
_next_id = 0
STALE_SECONDS = 60          # a request nobody claimed within a minute is dropped
ACK_SECONDS = 5             # a claim the helper doesn't confirm in 5s goes back in the queue


def _row(r):
    return {"id": r["id"], "room": r["room"], "link": r["link"], "title": r["title"],
            "position": r["position"], "requested_at": r["requested_at"].timestamp(),
            "status": r["status"], "message": r["message"], "from_start": r["from_start"]}


async def add_tune(room, link, title, position, who, from_start=False):
    global _next_id
    if _pool:
        async with _pool.acquire() as conn:
            r = await conn.fetchrow(
                "INSERT INTO tune_requests (room, link, title, position, requested_by, from_start) "
                "VALUES ($1, $2, $3, $4, $5, $6) RETURNING *", room, link, title, position, who, from_start)
        return _row(r)
    from datetime import datetime, timezone
    _next_id += 1
    _tunes[_next_id] = {"id": _next_id, "room": room, "link": link, "title": title, "position": position,
                        "requested_at": datetime.now(timezone.utc), "status": "pending", "message": None,
                        "from_start": from_start}
    return _row(_tunes[_next_id])


async def get_tune(tid):
    if _pool:
        async with _pool.acquire() as conn:
            r = await conn.fetchrow("SELECT * FROM tune_requests WHERE id = $1", tid)
        return _row(r) if r else None
    return _row(_tunes[tid]) if tid in _tunes else None


async def claim_tune():
    """Oldest pending request, marked claimed — or None. Expires stale ones first."""
    if _pool:
        async with _pool.acquire() as conn:
            # A claim handed to a helper that vanished (restart, network blip)
            # is never confirmed; after ACK_SECONDS it's someone else's to take.
            await conn.execute(
                "UPDATE tune_requests SET status = 'pending', updated_at = now() "
                "WHERE status = 'claimed' AND updated_at < now() - make_interval(secs => $1)",
                ACK_SECONDS)
            await conn.execute(
                "UPDATE tune_requests SET status = 'expired', updated_at = now() "
                "WHERE status = 'pending' AND requested_at < now() - make_interval(secs => $1)",
                STALE_SECONDS)
            r = await conn.fetchrow(
                "UPDATE tune_requests SET status = 'claimed', updated_at = now() WHERE id = ("
                " SELECT id FROM tune_requests WHERE status = 'pending' ORDER BY id LIMIT 1"
                " FOR UPDATE SKIP LOCKED) RETURNING *")
        return _row(r) if r else None
    import time as _t
    for t in _tunes.values():
        if t["status"] == "claimed" and _t.time() - t.get("claimed_at", 0) > ACK_SECONDS:
            t["status"] = "pending"
        if t["status"] == "pending" and _t.time() - t["requested_at"].timestamp() > STALE_SECONDS:
            t["status"] = "expired"
    for t in sorted(_tunes.values(), key=lambda t: t["id"]):
        if t["status"] == "pending":
            t["status"], t["claimed_at"] = "claimed", _t.time()
            return _row(t)
    return None


async def ack_tune(tid):
    """The helper confirms it has the request: claimed → working. False if the
    claim had already lapsed back to pending (then the helper should drop it)."""
    if _pool:
        async with _pool.acquire() as conn:
            r = await conn.execute("UPDATE tune_requests SET status = 'working', updated_at = now() "
                                   "WHERE id = $1 AND status = 'claimed'", tid)
        return r.endswith(" 1")
    if tid in _tunes and _tunes[tid]["status"] == "claimed":
        _tunes[tid]["status"] = "working"
        return True
    return False


async def finish_tune(tid, status, message):
    if _pool:
        async with _pool.acquire() as conn:
            await conn.execute("UPDATE tune_requests SET status = $2, message = $3, updated_at = now() "
                               "WHERE id = $1", tid, status, message)
    elif tid in _tunes:
        _tunes[tid].update(status=status, message=message)

