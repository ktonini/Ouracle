import pandas as pd
import logging
from typing import Any, Optional
from backend.src.models import Readiness, Resilience
from backend.src.ingestion.base import IngestionBase

logger = logging.getLogger("ReadinessProcessor")


def _normalize_level(val: Any) -> Optional[str]:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    text = str(val).strip()
    if not text or text.lower() == "nan":
        return None
    return text


class ReadinessProcessor(IngestionBase):
    def process_readiness(self, df: pd.DataFrame):
        if 'day' in df.columns:
            df = df.drop_duplicates(subset=['day'], keep='last')

        records = []
        for _, row in df.iterrows():
            day_val = self._parse_date(row.get('day'))
            if not day_val:
                continue

            contributors = self._parse_json_col(row.get('contributors')) or {}

            rec = Readiness(
                id=self._day_pk("readiness", day_val),
                day=day_val,
                score=self._parse_int(row.get('score')),
                temperature_deviation=self._parse_float(row.get('temperature_deviation')),
                temperature_trend_deviation=self._parse_float(row.get('temperature_trend_deviation')),
                contributors=contributors,
                stress_high=self._parse_int(row.get('stress_high')),
                recovery_high=self._parse_int(row.get('recovery_high')),
                day_summary=row.get('day_summary')
            )
            records.append(rec)
        
        self._upsert_content_aware(Readiness, records, ['day'])

    def _resilience_day(self, row) -> Optional[Any]:
        return self._parse_date(row.get('day')) or self._parse_date(row.get('date'))

    def _resilience_float(self, row, contributors: Optional[dict], *keys: str) -> Optional[float]:
        for key in keys:
            raw = row.get(key)
            if raw is not None and not (isinstance(raw, float) and pd.isna(raw)) and raw != "":
                parsed = self._parse_float(raw)
                if parsed is not None:
                    return parsed
        if contributors:
            for key in keys:
                if key in contributors and contributors[key] is not None:
                    parsed = self._parse_float(contributors[key])
                    if parsed is not None:
                        return parsed
        return None

    def process_resilience(self, df: pd.DataFrame):
        if "day" not in df.columns and "date" in df.columns:
            df = df.rename(columns={"date": "day"})
        if "day" in df.columns:
            df = df.drop_duplicates(subset=["day"], keep="last")

        records = []
        for _, row in df.iterrows():
            try:
                day_val = self._resilience_day(row)
                if not day_val:
                    continue

                contributors = self._parse_json_col(row.get("contributors")) or {}

                level = _normalize_level(row.get("level"))
                if level is None:
                    level = _normalize_level(row.get("resilience_level"))
                if level is None:
                    level = _normalize_level(row.get("resilience"))

                rec = Resilience(
                    id=self._day_pk("resilience", day_val),
                    day=day_val,
                    level=level,
                    sleep_recovery=self._resilience_float(
                        row, contributors, "sleep_recovery", "sleepRecovery"
                    ),
                    daytime_recovery=self._resilience_float(
                        row, contributors, "daytime_recovery", "daytimeRecovery"
                    ),
                    stress=self._resilience_float(
                        row, contributors, "stress", "stress_score"
                    ),
                )
                records.append(rec)
            except Exception as e:
                logger.error(f"Error parsing daily_resilience row: {e}")
                continue

        self._upsert_content_aware(Resilience, records, ["day"])
