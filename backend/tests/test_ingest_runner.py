"""Tests for ZIP ingestion helpers."""

from __future__ import annotations

from datetime import date

from backend.src.insights.sync_freshness import ingest_advanced_data


def test_ingest_advanced_data():
    assert ingest_advanced_data(date(2026, 5, 26), date(2026, 5, 28))
    assert not ingest_advanced_data(date(2026, 5, 26), date(2026, 5, 26))
