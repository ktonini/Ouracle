import os
import zipfile
import tempfile
import logging
import pandas as pd
from typing import Optional
from sqlalchemy.orm import Session
from .base import IngestionBase
from .state import IngestContext
from .processors.sleep import SleepProcessor
from .processors.activity import ActivityProcessor
from .processors.readiness import ReadinessProcessor
from .processors.common import CommonProcessor

logger = logging.getLogger("OuraParser")

class OuraParser(IngestionBase):
    def __init__(self, session: Session, ctx: Optional[IngestContext] = None):
        super().__init__(session, ctx)
        self.sleep_processor = SleepProcessor(session, ctx)
        self.activity_processor = ActivityProcessor(session, ctx)
        self.readiness_processor = ReadinessProcessor(session, ctx)
        self.common_processor = CommonProcessor(session, ctx)

    def parse_zip(self, zip_path: str):
        """Extracts ZIP and parses all contained CSVs, handling nested folders."""
        with tempfile.TemporaryDirectory() as temp_dir:
            try:
                with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                    zip_ref.extractall(temp_dir)
            except zipfile.BadZipFile:
                logger.error(f"Error: Invalid ZIP file at {zip_path}")
                return
            
            target_dir = temp_dir
            found_csvs = []
            for root, dirs, files in os.walk(temp_dir):
                if "dailysleep.csv" in files or "dailyactivity.csv" in files:
                    target_dir = root
                    found_csvs = files
                    break
            
            if not found_csvs:
                 logger.warning("No Oura CSV files found in the ZIP archive!")
            else:
                 logger.info(f"Found data in: {target_dir}")
            
            self.parse_directory(target_dir)

    def _should_process(self, filename: str, dir_path: str) -> bool:
        fpath = os.path.join(dir_path, filename)
        if not os.path.exists(fpath):
            return False
        if self.ctx is None:
            return True
        if self.ctx.should_skip_file(filename, fpath):
            logger.info("Skipping unchanged file %s", filename)
            return False
        return True

    def _any_should_process(self, filenames: list, dir_path: str) -> bool:
        return any(self._should_process(name, dir_path) for name in filenames)

    def parse_directory(self, dir_path: str):
        """Parses all supported CSV files in the directory, merging related files."""
        
        sleep_sources = ["dailysleep.csv", "sleeptime.csv", "dailyspo2.csv"]
        if self._any_should_process(sleep_sources, dir_path):
            sleep_df = self._read_csv_robust(os.path.join(dir_path, "dailysleep.csv"))
            sleeptime_df = self._read_csv_robust(os.path.join(dir_path, "sleeptime.csv"))
            spo2_df = self._read_csv_robust(os.path.join(dir_path, "dailyspo2.csv"))

            merged_sleep = sleep_df

            if sleeptime_df is not None and not sleeptime_df.empty:
                if merged_sleep is not None and not merged_sleep.empty:
                    if 'day' in merged_sleep.columns and 'day' in sleeptime_df.columns:
                        merged_sleep = pd.merge(merged_sleep, sleeptime_df, on='day', how='outer', suffixes=('', '_time'))
                else:
                    merged_sleep = sleeptime_df

            if spo2_df is not None and not spo2_df.empty:
                if merged_sleep is not None and not merged_sleep.empty:
                    if 'day' in merged_sleep.columns and 'day' in spo2_df.columns:
                        merged_sleep = pd.merge(merged_sleep, spo2_df, on='day', how='outer', suffixes=('', '_spo2'))
                else:
                    merged_sleep = spo2_df

            if merged_sleep is not None and not merged_sleep.empty:
                logger.info("Processing Sleep Data...")
                self.sleep_processor.process_sleep(merged_sleep)

        readiness_sources = ["dailyreadiness.csv", "dailystress.csv"]
        if self._any_should_process(readiness_sources, dir_path):
            readiness_df = self._read_csv_robust(os.path.join(dir_path, "dailyreadiness.csv"))
            stress_df = self._read_csv_robust(os.path.join(dir_path, "dailystress.csv"))

            if readiness_df is not None and not readiness_df.empty:
                if stress_df is not None and not stress_df.empty:
                    if 'day' in readiness_df.columns and 'day' in stress_df.columns:
                        merged_readiness = pd.merge(readiness_df, stress_df, on='day', how='outer', suffixes=('', '_stress'))
                        logger.info("Processing Readiness Data...")
                        self.readiness_processor.process_readiness(merged_readiness)
                    else:
                        self.readiness_processor.process_readiness(readiness_df)
                else:
                    logger.info("Processing Readiness Data...")
                    self.readiness_processor.process_readiness(readiness_df)
            elif stress_df is not None and not stress_df.empty:
                logger.info("Processing dailystress.csv as Readiness...")
                self.readiness_processor.process_readiness(stress_df)

        if self._should_process("dailyactivity.csv", dir_path):
            act_df = self._read_csv_robust(os.path.join(dir_path, "dailyactivity.csv"))
            if act_df is not None and not act_df.empty:
                logger.info("Processing Activity Data...")
                self.activity_processor.process_activity(act_df)

        resilience_sources = ["dailyresilience.csv", "daily_resilience.csv", "resilience.csv"]
        if self._any_should_process(resilience_sources, dir_path):
            frames = []
            for name in resilience_sources:
                res_df = self._read_csv_robust(os.path.join(dir_path, name))
                if res_df is not None and not res_df.empty:
                    if "day" not in res_df.columns and "date" in res_df.columns:
                        res_df = res_df.rename(columns={"date": "day"})
                    frames.append(res_df)
            if frames:
                merged_resilience = pd.concat(frames, ignore_index=True)
                if "day" in merged_resilience.columns:
                    merged_resilience = merged_resilience.drop_duplicates(
                        subset=["day"], keep="last"
                    )
                logger.info("Processing Resilience Data...")
                self.readiness_processor.process_resilience(merged_resilience)

        if self._should_process("daytimestress.csv", dir_path):
            day_stress_df = self._read_csv_robust(os.path.join(dir_path, "daytimestress.csv"))
            if day_stress_df is not None and not day_stress_df.empty:
                self.activity_processor.process_stress(day_stress_df)

        path_map = {
            "sleepmodel.csv": self.sleep_processor.process_sleep_session,
            "workout.csv": self.activity_processor.process_workout,
            "session.csv": self.activity_processor.process_meditation,
            "heartrate.csv": self.common_processor.process_heart_rate,
            "temperature.csv": self.common_processor.process_temperature,
        }

        for filename, func in path_map.items():
            if self._should_process(filename, dir_path):
                logger.info(f"Processing {filename}...")
                func(os.path.join(dir_path, filename))

        common_map = {
            "ringconfiguration.csv": self.common_processor.process_ring_configuration,
            "enhancedtag.csv": self.common_processor.process_tag,
            "dailycardiovascularage.csv": self.common_processor.process_cardiovascular_age,
            "ringbatterylevel.csv": self.common_processor.process_ring_battery,
        }

        for filename, func in common_map.items():
            fpath = os.path.join(dir_path, filename)
            if not os.path.exists(fpath):
                continue
            if self.ctx and self.ctx.should_skip_file(filename, fpath):
                logger.info("Skipping unchanged file %s", filename)
                continue
            if filename == "enhancedtag.csv" and self.ctx and self.ctx.effective_incremental:
                self.ctx.counts.files_processed += 1
            df = self._read_csv_robust(fpath)
            if df is not None and not df.empty:
                logger.info(f"Processing {filename}...")
                func(df)
