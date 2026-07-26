import pandas as pd
import json
import os
import logging
from datetime import datetime, date
from typing import List, Any, Type, Optional, TYPE_CHECKING
from sqlalchemy.orm import Session
from sqlalchemy.dialects.sqlite import insert
from backend.src.models import Base
from backend.src.ingestion.state import content_columns_for, content_differs, synthetic_id, naive_utc

if TYPE_CHECKING:
    from backend.src.ingestion.state import IngestContext

# Configure Logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("IngestionBase")
SQLITE_SAFE_VARIABLE_LIMIT = 900

class IngestionBase:
    """
    Base class for Oura Data Ingestion.
    Provides robust CSV reading (handling bad quotes/mismatched columns) and batch upserting for SQLite.
    """
    def __init__(self, session: Session, ctx: Optional["IngestContext"] = None):
        self.session = session
        self.ctx = ctx

    def _synthetic_id(self, entity: str, fields: list) -> str:
        return synthetic_id(entity, fields)

    def _oura_or_synthetic(
        self,
        row,
        entity: str,
        synthetic_fields: list,
        oura_col: str = "id",
    ) -> str:
        oura_id = row.get(oura_col) if hasattr(row, "get") else getattr(row, oura_col, None)
        if oura_id is None or pd.isna(oura_id) or str(oura_id).strip().lower() in ("", "nan"):
            return self._synthetic_id(entity, synthetic_fields)
        return str(oura_id)

    def _day_pk(self, table: str, day_val: date) -> str:
        return self._synthetic_id(table, [day_val])

    def _record_counts(self, inserted: int = 0, updated: int = 0, unchanged: int = 0, skipped: int = 0) -> None:
        if self.ctx is None:
            return
        self.ctx.counts.inserted += inserted
        self.ctx.counts.updated += updated
        self.ctx.counts.unchanged += unchanged
        self.ctx.counts.skipped += skipped

    def _read_csv_robust(self, file_path: str) -> Optional[pd.DataFrame]:
        """Reads CSV handling Oura's sometimes malformed quoting and mismatched column counts."""
        if not os.path.exists(file_path):
            return None
            
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        if not lines:
            return None

        # Parse header
        header = lines[0].strip().split(';')
        raw_data_lines = lines[1:]
        
        # Heuristic for specific Oura files known to have column alignment issues
        if 'dailyactivity.csv' in file_path.lower() or 'sleepmodel.csv' in file_path.lower():
            # Check for column mismatch in first data row
            if raw_data_lines and len(header) > len(raw_data_lines[0].split(';')):
                # Data is often aligned to the end (missing start columns)
                offset = len(header) - len(raw_data_lines[0].split(';'))
                
                new_rows = []
                for line in raw_data_lines:
                    line = line.strip()
                    if not line: continue
                    
                    # Remove wrapping quotes
                    if line.startswith('"') and line.endswith('"'):
                        line = line[1:-1]
                        
                    parts = line.split(';')
                    # Pad missing start columns with None
                    padded_parts = [None] * offset + parts
                    new_rows.append(padded_parts)
                
                df = pd.DataFrame(new_rows, columns=header)
                self._clean_dataframe(df)
                return df

        # Standard processing for other files
        data = []
        for line in raw_data_lines:
            line = line.strip()
            if not line: continue
            
            if line.startswith('"') and line.endswith('"'):
                line = line[1:-1]
            
            parts = line.split(';')
            
            # Missing id column — processors derive deterministic keys
            if len(parts) == len(header) - 1 and header[0] == 'id':
                parts.insert(0, "")
            
            # Handle trailing empty columns
            if len(parts) < len(header):
                parts += [None] * (len(header) - len(parts))
            
            # Truncate extra columns
            if len(parts) > len(header):
                 parts = parts[:len(header)]
                 
            data.append(parts)
            
        df = pd.DataFrame(data, columns=header)
        self._clean_dataframe(df)
        return df

    def _clean_dataframe(self, df: pd.DataFrame):
        """Standardizes dataframe values (stripping extra quotes)."""
        for col in df.columns:
            df[col] = df[col].apply(lambda x: x.strip('"') if isinstance(x, str) else x)

    def _upsert(self, model: Type[Base], data: List[Any], index_elements: List[str]):
        """
        Generic SQLite upsert (INSERT OR REPLACE) implementation.
        """
        if not data:
            return

        # Convert ORM objects to dicts if needed
        if isinstance(data[0], model):
            clean_data = []
            for obj in data:
                row_dict = {}
                for col in model.__table__.columns:
                     val = getattr(obj, col.name)
                     row_dict[col.name] = val
                clean_data.append(row_dict)
            data = clean_data

        columns_per_row = max(1, len(data[0]))
        max_batch_size = max(1, SQLITE_SAFE_VARIABLE_LIMIT // columns_per_row)
        if len(data) > max_batch_size:
            logger.info(
                "Splitting %s records for %s into batches of %s to stay under SQLite variable limits.",
                len(data),
                model.__tablename__,
                max_batch_size,
            )
            for i in range(0, len(data), max_batch_size):
                self._upsert(model, data[i : i + max_batch_size], index_elements)
            return

        try:
            stmt = insert(model).values(data)
            
            # Columns to update on conflict (all except the index/primary key)
            update_dict = {col.name: col for col in stmt.excluded if col.name not in index_elements}
            
            if update_dict:
                stmt = stmt.on_conflict_do_update(
                    index_elements=index_elements,
                    set_=update_dict
                )
            else:
                stmt = stmt.on_conflict_do_nothing(index_elements=index_elements)

            self.session.execute(stmt)
            self.session.commit()
        except Exception as e:
            self.session.rollback()
            logger.error(f"Error in _upsert for {model.__tablename__}: {e}")
            if data:
                logger.debug(f"First record sample: {data[0]}")
            raise

    def _batch_upsert(self, model: Type[Base], data: List[Any], index_elements: List[str], batch_size=1000):
        """Batch upsert wrapper to avoid SQLite limit restrictions."""
        if not data:
            return

        total_records = len(data)
        logger.info(f"Upserting {total_records} records into {model.__tablename__}...")
        
        for i in range(0, total_records, batch_size):
            batch = data[i : i + batch_size]
            self._upsert(model, batch, index_elements)

    def _upsert_content_aware(
        self,
        model: Type[Base],
        records: List[Any],
        index_elements: List[str],
    ) -> None:
        if not records:
            return
        ctx = self.ctx
        if ctx is None or not ctx.effective_incremental:
            self._upsert(model, records, index_elements)
            self._record_counts(inserted=len(records))
            return

        key_col = index_elements[0]
        keys = [getattr(r, key_col) for r in records]
        existing_rows = (
            self.session.query(model)
            .filter(getattr(model, key_col).in_(keys))
            .all()
        )
        existing = {getattr(r, key_col): r for r in existing_rows}
        cols = content_columns_for(model)
        to_write: List[Any] = []
        ins = upd = unchanged = 0
        for rec in records:
            k = getattr(rec, key_col)
            old = existing.get(k)
            if old is None:
                ins += 1
                to_write.append(rec)
            elif content_differs(old, rec, cols):
                upd += 1
                to_write.append(rec)
            else:
                unchanged += 1
        self._record_counts(inserted=ins, updated=upd, unchanged=unchanged)
        if to_write:
            self._upsert(model, to_write, index_elements)

    # --- Parsing Helpers ---

    def _parse_json_col(self, val):
        if pd.isna(val) or val == "" or val == 'null':
            return None
        if isinstance(val, str):
            try:
                # Handle CSV double-quote escaping
                val = val.replace('""', '"')
                if val.startswith('"') and val.endswith('"'):
                    val = val[1:-1]
                return json.loads(val)
            except json.JSONDecodeError:
                return None
        return val

    def _parse_datetime(self, val):
        if pd.isna(val) or val == "":
            return None
        if isinstance(val, datetime):
            return naive_utc(val)
        if isinstance(val, pd.Timestamp):
            return naive_utc(val.to_pydatetime())
        if isinstance(val, str):
            val = val.replace('"', '')
        try:
            return naive_utc(pd.to_datetime(val, format='ISO8601').to_pydatetime())
        except Exception:
            try:
                return naive_utc(pd.to_datetime(val).to_pydatetime())
            except Exception:
                return None

    def _parse_date(self, val):
        if pd.isna(val) or val == "":
            return None
        if isinstance(val, date):
            return val
        if isinstance(val, str):
            val = val.replace('"', '')
        try:
            return pd.to_datetime(val).date()
        except Exception:
            return None

    def _parse_float(self, val):
        if val is None or val == "":
            return None
        try:
            return float(val)
        except ValueError:
            return None

    def _parse_int(self, val):
        if val is None or val == "":
            return None
        try:
            # Handle "100.0" strings as 100
            return int(float(val))
        except ValueError:
            return None

    def _parse_sequence_to_timestamped_list(self, val, start_time: datetime, interval_seconds: int):
        """
        Robustly parses various sequence formats (JSON, AST, comma-separated) 
        into a uniform list of timestamped objects for the frontend.
        """
        if pd.isna(val) or val == "":
            return None
        
        if isinstance(val, (int, float)):
            val = str(int(val))

        items = None
        if isinstance(val, (dict, list)):
             if isinstance(val, dict) and 'items' in val:
                 items = val['items']
             elif isinstance(val, list):
                 items = val
        elif isinstance(val, str):
            val_str = val.strip()
            if not val_str:
                return None

            # Handle CSV double-quote escaping (e.g. ""key"" -> "key")
            val_str = val_str.replace('""', '"')
            if val_str.startswith('"') and val_str.endswith('"'):
                val_str = val_str[1:-1]

            # 1. JSON parse
            try:
                parsed = json.loads(val_str)
                if isinstance(parsed, dict) and 'items' in parsed:
                    items = parsed['items']
                elif isinstance(parsed, list):
                    items = parsed
            except json.JSONDecodeError:
                pass

            if items is None:
                # 2. Fallback: AST literal eval (only if it looks like a list)
                try:
                    if val_str.strip().startswith('['):
                        import ast
                        parsed = ast.literal_eval(val_str)
                        if isinstance(parsed, list):
                            items = parsed
                except Exception:
                    pass

            if items is None:
                # 3. Fallback: Split/Clean (Handle digit strings "4422" or comma-separated)
                val_cleaned = val_str.replace('"', '').replace("'", "")
                if ',' in val_cleaned:
                        try:
                            items = [float(x.strip()) for x in val_cleaned.strip('[]').split(',') if x.strip()]
                        except Exception:
                            pass
                else:
                    # Hypnogram string case: "4422233"
                    try:
                        items = [int(c) for c in val_cleaned if c.isdigit()]
                    except Exception:
                        pass

        if not items:
            return None

        result = []
        for i, item in enumerate(items):
            ts = start_time + pd.Timedelta(seconds=i * interval_seconds)
            
            if isinstance(item, dict):
                val_to_store = item.copy()
                val_to_store['timestamp'] = ts.isoformat()
            else:
                val_to_store = {
                    "timestamp": ts.isoformat(),
                    "value": item
                }
            result.append(val_to_store)
            
        return result
