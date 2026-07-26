import pandas as pd
import logging
from backend.src.models import HeartRate, Temperature, RingConfiguration, Tag, CardiovascularAge, RingBattery
from backend.src.ingestion.base import IngestionBase
from backend.src.ingestion.state import is_before

logger = logging.getLogger("CommonProcessor")

class CommonProcessor(IngestionBase):
    def _filter_high_frequency(
        self,
        df: pd.DataFrame,
        entity: str,
        ts_col: str = "timestamp",
    ) -> pd.DataFrame:
        cutoff = self.ctx.cutoff_for(entity) if self.ctx else None
        if cutoff is None:
            return df
        skipped = 0
        keep = []
        for _, row in df.iterrows():
            ts = self._parse_datetime(row.get(ts_col))
            if is_before(ts, cutoff):
                skipped += 1
                continue
            keep.append(row)
        self._record_counts(skipped=skipped)
        if not keep:
            return df.iloc[0:0]
        return pd.DataFrame(keep).reset_index(drop=True)

    def process_heart_rate(self, file_path: str):
        df = self._read_csv_robust(file_path)
        if df is None or df.empty:
            return
        df = self._filter_high_frequency(df, "heart_rate")

        records = []
        for _, row in df.iterrows():
            try:
                bpm = self._parse_int(row.get('bpm'))
                if bpm is None:
                    continue
                hr = HeartRate(
                    timestamp=self._parse_datetime(row.get('timestamp')),
                    bpm=bpm,
                    source=row.get('source') or ''
                )
                records.append(hr)
            except Exception:
                continue
        
        if records:
            self._batch_upsert(HeartRate, records, ['timestamp'])
            self._record_counts(inserted=len(records))

    def process_temperature(self, file_path: str):
        df = self._read_csv_robust(file_path)
        if df is None or df.empty:
            return
        df = self._filter_high_frequency(df, "temperature")

        records = []
        for _, row in df.iterrows():
            try:
                skin_temp = self._parse_float(row.get('skin_temp'))
                if skin_temp is None:
                    continue

                temp = Temperature(
                    timestamp=self._parse_datetime(row.get('timestamp')),
                    skin_temp=skin_temp
                )
                records.append(temp)
            except Exception:
                continue
        
        if records:
            self._batch_upsert(Temperature, records, ['timestamp'])
            self._record_counts(inserted=len(records))

    def process_ring_battery(self, df: pd.DataFrame):
        df = self._filter_high_frequency(df, "ring_battery")
        records = []
        for _, row in df.iterrows():
            try:
                batt = RingBattery(
                    timestamp=self._parse_datetime(row.get('timestamp')),
                    level=self._parse_int(row.get('level')),
                    charging=bool(self._parse_int(row.get('charging'))),
                    in_charger=bool(self._parse_int(row.get('in_charger')))
                )
                records.append(batt)
            except Exception:
                pass
        
        if records:
            self._batch_upsert(RingBattery, records, ['timestamp'])
            self._record_counts(inserted=len(records))

    def process_ring_configuration(self, df: pd.DataFrame):
        records = []
        for _, row in df.iterrows():
            try:
                conf = RingConfiguration(
                    id=self._oura_or_synthetic(
                        row,
                        "ring_configuration",
                        [
                            row.get('firmware_version'),
                            row.get('hardware_type'),
                            row.get('color'),
                            row.get('size'),
                        ],
                    ),
                    firmware_version=row.get('firmware_version'),
                    size=self._parse_int(row.get('size')),
                    color=row.get('color'),
                    hardware_type=row.get('hardware_type')
                )
                records.append(conf)
            except Exception:
                pass
        self._upsert_content_aware(RingConfiguration, records, ['id'])

    def process_tag(self, df: pd.DataFrame):
        records = []
        for _, row in df.iterrows():
            try:
                tag = Tag(
                    id=self._oura_or_synthetic(
                        row,
                        "tag",
                        [
                            self._parse_datetime(row.get('start_time')),
                            row.get('tag_type_code'),
                            row.get('comment'),
                        ],
                    ),
                    start_time=self._parse_datetime(row.get('start_time')),
                    end_time=self._parse_datetime(row.get('end_time')),
                    tag_type_code=row.get('tag_type_code'),
                    comment=row.get('comment')
                )
                records.append(tag)
            except Exception:
                pass
        self._upsert_content_aware(Tag, records, ['id'])

    def process_cardiovascular_age(self, df: pd.DataFrame):
        records = []
        for _, row in df.iterrows():
            try:
                day_val = self._parse_date(row.get('day'))
                if not day_val:
                    continue
                rec = CardiovascularAge(
                    id=self._day_pk("cardiovascular_age", day_val),
                    day=day_val,
                    vascular_age=self._parse_int(row.get('vascular_age'))
                )
                records.append(rec)
            except Exception:
                pass
        self._upsert_content_aware(CardiovascularAge, records, ['day'])
