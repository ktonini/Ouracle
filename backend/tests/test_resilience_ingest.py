"""Tests for resilience CSV ingestion."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
from backend.src.ingestion.manager import OuraParser
from backend.src.ingestion.processors.readiness import ReadinessProcessor
from backend.src.models import Resilience


def _processor(db_session) -> ReadinessProcessor:
    return ReadinessProcessor(db_session)


def test_top_level_resilience_values_inserted(db_session):
    df = pd.DataFrame(
        [
            {
                "day": "2026-02-16",
                "level": "Solid",
                "sleep_recovery": 85.0,
                "daytime_recovery": 70.0,
                "stress": 30.0,
            }
        ]
    )
    _processor(db_session).process_resilience(df)
    row = db_session.query(Resilience).filter(Resilience.day == date(2026, 2, 16)).one()
    assert row.level == "Solid"
    assert row.sleep_recovery == 85.0
    assert row.daytime_recovery == 70.0
    assert row.stress == 30.0


def test_contributor_json_resilience_values_inserted(db_session):
    df = pd.DataFrame(
        [
            {
                "day": "2026-02-17",
                "level": "Strong",
                "contributors": (
                    '{"sleep_recovery": 90, "daytime_recovery": 65, "stress": 25}'
                ),
            }
        ]
    )
    _processor(db_session).process_resilience(df)
    row = db_session.query(Resilience).filter(Resilience.day == date(2026, 2, 17)).one()
    assert row.level == "Strong"
    assert row.sleep_recovery == 90.0
    assert row.daytime_recovery == 65.0
    assert row.stress == 25.0


def test_duplicate_days_keep_last_row(db_session):
    df = pd.DataFrame(
        [
            {
                "day": "2026-02-18",
                "level": "Adequate",
                "sleep_recovery": 50.0,
                "daytime_recovery": 50.0,
                "stress": 50.0,
            },
            {
                "day": "2026-02-18",
                "level": "Exceptional",
                "sleep_recovery": 99.0,
                "daytime_recovery": 88.0,
                "stress": 10.0,
            },
        ]
    )
    _processor(db_session).process_resilience(df)
    rows = db_session.query(Resilience).filter(Resilience.day == date(2026, 2, 18)).all()
    assert len(rows) == 1
    assert rows[0].level == "Exceptional"
    assert rows[0].sleep_recovery == 99.0


def test_manager_merges_resilience_filenames(db_session, tmp_path: Path):
    export_dir = tmp_path / "export"
    export_dir.mkdir()
    (export_dir / "dailyresilience.csv").write_text(
        "day;level;sleep_recovery;daytime_recovery;stress\n"
        "2026-02-19;Solid;80;70;20\n",
        encoding="utf-8",
    )
    (export_dir / "resilience.csv").write_text(
        "day;level;sleep_recovery;daytime_recovery;stress\n"
        "2026-02-19;Exceptional;95;90;5\n"
        "2026-02-20;Strong;75;65;15\n",
        encoding="utf-8",
    )
    OuraParser(db_session).parse_directory(str(export_dir))
    feb19 = db_session.query(Resilience).filter(Resilience.day == date(2026, 2, 19)).one()
    assert feb19.level == "Exceptional"
    feb20 = db_session.query(Resilience).filter(Resilience.day == date(2026, 2, 20)).one()
    assert feb20.level == "Strong"
