"""Nightly retrain of the sleep-staging model.

Every night the cloud scores becomes another ~90 labelled epochs, so the model
should improve on its own rather than waiting for someone to run a command.

    python -m backend.src.ring_events.retrain

Does nothing when no new night has appeared, and refuses to install a model
that fails to beat the trivial baseline or that is materially worse than the
one already running — this runs unattended, so it must not be able to quietly
replace a good model with a bad one.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from ..paths import get_user_data_dir
from .training import _by_night, build_dataset, train_model

logger = logging.getLogger("RingRetrain")


def installed_meta() -> Dict[str, Any]:
    """Metadata of the model currently in place, if any."""
    path = get_user_data_dir() / "sleep_model.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text()).get("meta") or {}
    except Exception:
        logger.warning("could not read %s; treating as untrained", path)
        return {}


def retrain(db: Session, force: bool = False) -> Dict[str, Any]:
    """Retrain when there is something new to learn from."""
    dataset = build_dataset(db)
    if not dataset:
        return {"trained": False, "reason": "no paired nights yet"}

    nights = sorted(_by_night(dataset))
    meta = installed_meta()

    if not force and meta.get("nights") == nights and meta.get("epochs") == len(dataset):
        return {
            "trained": False,
            "reason": "no new nights since the last fit",
            "nights": len(nights),
        }

    result = train_model(db, dataset=dataset, guard=not force)
    result["known_nights"] = len(nights)
    result["new_nights"] = sorted(set(nights) - set(meta.get("nights") or []))
    return result


def main(argv: Optional[List[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force", action="store_true",
        help="Retrain even with nothing new, and skip the quality guard.",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")

    from ..database import SessionLocal, init_db

    init_db()
    db = SessionLocal()
    try:
        # Check the feed before the model: a night missing from the ring is the
        # difference between the model improving and it standing still, and the
        # drain cannot be trusted to notice on its own.
        from .audit import coverage_report

        coverage = coverage_report(db)
        logger.info("coverage %s: %s", coverage["status"], coverage["message"])
        if coverage["status"] == "gaps":
            try:
                from ..notify import notify

                notify(db, "Ouracle: ring data missing", coverage["message"])
            except Exception:
                logger.exception("could not send the coverage alert")

        result = retrain(db, force=args.force)
        if result.get("trained"):
            logger.info(
                "retrained on %d nights / %d epochs: balanced %s (baseline %s, was %s)",
                result.get("nights"), result.get("epochs"), result.get("balanced"),
                result.get("baseline"), result.get("previous_balanced"),
            )
            if result.get("new_nights"):
                logger.info("new nights: %s", ", ".join(result["new_nights"]))
        else:
            logger.info("not retrained: %s", result.get("reason"))
            # A refusal on quality grounds is worth knowing about; "nothing
            # new" is the normal case and stays quiet.
            if "beat" in str(result.get("reason")) or "worse" in str(result.get("reason")):
                try:
                    from ..notify import notify

                    notify(
                        db,
                        "Ouracle: staging model not updated",
                        str(result.get("reason")),
                    )
                except Exception:
                    logger.exception("could not send the alert")
                return 1
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
