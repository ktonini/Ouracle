"""Build minimal Oura-export ZIP fixtures for ingest tests."""

from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Optional


def _csv_line(header: str, row: str) -> str:
    return f"{header}\n{row}\n"


def write_export_dir(
    tmp_path: Path,
    *,
    dailysleep: Optional[str] = None,
    dailyactivity: Optional[str] = None,
    dailyreadiness: Optional[str] = None,
    heartrate: Optional[str] = None,
) -> Path:
    """Write semicolon-delimited CSVs into a directory."""
    if dailysleep is not None:
        (tmp_path / "dailysleep.csv").write_text(dailysleep, encoding="utf-8")
    if dailyactivity is not None:
        (tmp_path / "dailyactivity.csv").write_text(dailyactivity, encoding="utf-8")
    if dailyreadiness is not None:
        (tmp_path / "dailyreadiness.csv").write_text(dailyreadiness, encoding="utf-8")
    if heartrate is not None:
        (tmp_path / "heartrate.csv").write_text(heartrate, encoding="utf-8")
    return tmp_path


def zip_directory(dir_path: Path, zip_path: Path) -> Path:
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in dir_path.iterdir():
            if f.is_file():
                zf.write(f, arcname=f.name)
    return zip_path


def minimal_sleep_csv(day: str, score: int = 80) -> str:
    return _csv_line("id;day;score", f";{day};{score}")


def minimal_activity_csv(day: str, score: int = 70) -> str:
    return _csv_line("id;day;score;steps", f";{day};{score};5000")


def minimal_readiness_csv(day: str, score: int = 75) -> str:
    return _csv_line("id;day;score", f";{day};{score}")


def minimal_heartrate_csv(rows: list[tuple[str, int]]) -> str:
    """Rows are (ISO timestamp, bpm). Timestamps may include timezone offsets."""
    lines = ["timestamp;bpm;source"]
    for ts, bpm in rows:
        lines.append(f"{ts};{bpm};rest")
    return "\n".join(lines) + "\n"
