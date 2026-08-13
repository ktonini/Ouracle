"""Recover events hidden inside mis-split rows.

The phone's frame splitter read a notification's tag but ignored its length
byte, so when the ring packed several events into one packet everything after
the first was glued onto the first one's body. Those events were stored — just
not as themselves, and invisible to every reader.

The splitter is fixed, but the ring's history buffer holds only a day or two,
so the affected rows can't be re-synced. This unpacks them in place.

    python -m backend.src.ring_events.repair          # report only
    python -m backend.src.ring_events.repair --apply  # rewrite

A row is only rewritten when the tail parses as a run of `<tag><length>
<timestamp×4><body>` frames that consumes it exactly to the end, every tag is
a plausible event, and every timestamp sits near the parent's. Anything less
is left alone: a mangled row is worse than an opaque one.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from ..models import RingEventRaw

logger = logging.getLogger("RingRepair")

# History events occupy this tag range; anything else in the stream is a
# command response and never appears as a packed sub-event.
MIN_EVENT_TAG = 0x41
MAX_EVENT_TAG = 0x8F
# A packed run comes off one drain, so its events share a moment in ring time.
# Generous enough for a long packet, tight enough that random bytes fail.
MAX_TIMESTAMP_DRIFT_DS = 20_000

Packed = Tuple[bytes, List[Tuple[int, int, bytes]]]


def _parse_frames(body: bytes, start: int, parent_ts: int) -> Optional[List[Tuple[int, int, bytes]]]:
    """Parse `body[start:]` as framed events, or None if it doesn't fit exactly."""
    index = start
    events: List[Tuple[int, int, bytes]] = []
    while index + 6 <= len(body):
        tag, length = body[index], body[index + 1]
        if not MIN_EVENT_TAG <= tag <= MAX_EVENT_TAG:
            return None
        if length < 4 or index + 2 + length > len(body):
            return None
        timestamp = int.from_bytes(body[index + 2 : index + 6], "little")
        if abs(timestamp - parent_ts) > MAX_TIMESTAMP_DRIFT_DS:
            return None
        events.append((tag, timestamp, body[index + 6 : index + 2 + length]))
        index += 2 + length
    # Must land exactly on the end: a leftover tail means we guessed wrong.
    if index != len(body) or not events:
        return None
    return events


def split_packed(body: bytes, parent_ts: int) -> Optional[Packed]:
    """Split a row into its own body plus the events packed behind it.

    Returns None when the row is a normal single event.
    """
    if len(body) < 8:
        return None
    for split in range(len(body) - 5):
        events = _parse_frames(body, split, parent_ts)
        if events is not None:
            return body[:split], events
    return None


def repair_packed(db: Session, apply: bool = False) -> Dict[str, Any]:
    """Unpack every mis-split row. Reports what it would do unless `apply`."""
    rows_hit = 0
    recovered: Dict[int, int] = {}
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    for row in db.query(RingEventRaw).order_by(RingEventRaw.timestamp).all():
        if not row.body:
            continue
        found = split_packed(bytes.fromhex(row.body), row.timestamp)
        if found is None:
            continue
        own_body, events = found
        rows_hit += 1
        for tag, _, _ in events:
            recovered[tag] = recovered.get(tag, 0) + 1

        if not apply:
            continue

        # The parent keeps only what was really its own, and loses its decode
        # so the next decode pass reads the corrected body.
        row.body = own_body.hex()
        row.decoded = None
        for tag, timestamp, sub_body in events:
            db.merge(
                RingEventRaw(
                    id=f"{tag:02x}-{timestamp}",
                    tag=tag,
                    timestamp=timestamp,
                    body=sub_body.hex(),
                    received_at=now,
                )
            )

    if apply:
        db.commit()

    return {
        "rows_repaired": rows_hit,
        "events_recovered": sum(recovered.values()),
        "by_tag": dict(sorted(recovered.items())),
        "applied": apply,
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true", help="Rewrite rows (default: report only)."
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")

    from ..database import SessionLocal, init_db
    from .decoders import EVENT_NAMES
    from .runner import decode_stored

    init_db()
    db = SessionLocal()
    try:
        result = repair_packed(db, apply=args.apply)
        logger.info(
            "%s %d rows, %d events recovered",
            "repaired" if args.apply else "would repair",
            result["rows_repaired"],
            result["events_recovered"],
        )
        for tag, count in sorted(result["by_tag"].items(), key=lambda kv: -kv[1]):
            logger.info("  0x%02x %-30s %6d", tag, EVENT_NAMES.get(tag, "?"), count)
        if args.apply:
            counts = decode_stored(db)
            logger.info("decoded %d events after repair", sum(counts.values()))
        else:
            logger.info("nothing written — pass --apply to rewrite")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
