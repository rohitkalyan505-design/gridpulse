"""
GridPulse — Ingestion Module Parser
Boundary parser for normalizing raw electrical telemetry payloads into RawTelemetryBatch.
Operates purely in-memory with zero external network or database dependencies.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union

from scientific.contracts.issues import ProcessingIssue, TelemetryValidationError
from scientific.contracts.enums import IssueSeverity
from scientific.ingestion.contracts import (
    RawTelemetryBatch,
    RawTelemetryReading,
    RawTelemetryRecord,
)


def parse_raw_telemetry_batch(
    payload: Dict[str, Any],
    strict: bool = False,
) -> RawTelemetryBatch:
    """
    Parses a raw structured dictionary payload into a validated RawTelemetryBatch.

    Expected payload structure:
    {
        "asset_id": "TX-01",
        "nominal_interval_seconds": 60,
        "source_format": "JSON",
        "records": [
            {
                "timestamp": "2026-09-23T12:00:00Z" (or datetime),
                "readings": [
                    {
                        "channel_tag": "voltage_a",
                        "raw_value": 230.5,
                        "source_unit": "V",
                        "timestamp": "2026-09-23T12:00:00Z" (optional, defaults to record timestamp),
                        "sensor_id": "PT-01" (optional),
                        "raw_status_flag": "OK" (optional)
                    }
                ],
                "metadata": {} (optional)
            }
        ]
    }
    """
    if not isinstance(payload, dict):
        raise TelemetryValidationError(f"Payload must be a dictionary, got {type(payload).__name__}.")

    asset_id = payload.get("asset_id")
    if not asset_id or not isinstance(asset_id, str) or not asset_id.strip():
        raise TelemetryValidationError("Missing or invalid 'asset_id' in raw telemetry payload.")

    nominal_interval = payload.get("nominal_interval_seconds", 60)
    if not isinstance(nominal_interval, int) or nominal_interval <= 0:
        raise TelemetryValidationError(
            f"'nominal_interval_seconds' must be a strictly positive integer, got {nominal_interval}."
        )

    raw_records = payload.get("records")
    if raw_records is None or not isinstance(raw_records, list):
        raise TelemetryValidationError("Payload must contain a 'records' list.")

    parsed_records: List[RawTelemetryRecord] = []

    for idx, rec_dict in enumerate(raw_records):
        if not isinstance(rec_dict, dict):
            if strict:
                raise TelemetryValidationError(f"Record at index {idx} must be a dictionary.")
            continue

        raw_ts = rec_dict.get("timestamp")
        record_ts: Optional[datetime] = None
        if isinstance(raw_ts, datetime):
            record_ts = raw_ts
        elif isinstance(raw_ts, str):
            try:
                # Handle ISO 8601 strings (replace trailing Z with UTC timezone)
                cleaned_ts = raw_ts.replace("Z", "+00:00") if raw_ts.endswith("Z") else raw_ts
                record_ts = datetime.fromisoformat(cleaned_ts)
            except Exception as ex:
                if strict:
                    raise TelemetryValidationError(
                        f"Malformed timestamp '{raw_ts}' in record {idx}: {ex}"
                    ) from ex
                continue
        else:
            if strict:
                raise TelemetryValidationError(f"Missing or invalid 'timestamp' in record {idx}.")
            continue

        # Enforce timezone awareness
        if record_ts.tzinfo is None:
            if strict:
                raise TelemetryValidationError(
                    f"Record at index {idx} has timezone-naive timestamp '{raw_ts}'. Must be timezone-aware UTC."
                )
            continue

        readings_list: List[RawTelemetryReading] = []
        raw_readings = rec_dict.get("readings", [])
        if not isinstance(raw_readings, list):
            if strict:
                raise TelemetryValidationError(f"'readings' in record {idx} must be a list.")
            continue

        for r_idx, r_dict in enumerate(raw_readings):
            if not isinstance(r_dict, dict):
                if strict:
                    raise TelemetryValidationError(
                        f"Reading at index {r_idx} in record {idx} must be a dictionary."
                    )
                continue

            channel_tag = r_dict.get("channel_tag")
            if not channel_tag or not isinstance(channel_tag, str) or not channel_tag.strip():
                if strict:
                    raise TelemetryValidationError(
                        f"Reading {r_idx} in record {idx} is missing 'channel_tag'."
                    )
                continue

            raw_val = r_dict.get("raw_value")
            # raw_val can be None (missing data) or numeric
            numeric_val: Optional[float] = None
            if raw_val is not None:
                try:
                    numeric_val = float(raw_val)
                except (ValueError, TypeError) as ex:
                    if strict:
                        raise TelemetryValidationError(
                            f"Invalid numeric value '{raw_val}' for channel '{channel_tag}': {ex}"
                        ) from ex
                    # In fault-tolerant mode, preserve as None or bad
                    numeric_val = None

            source_unit = r_dict.get("source_unit", "")
            if not isinstance(source_unit, str):
                source_unit = str(source_unit)

            reading_ts = record_ts
            if "timestamp" in r_dict and r_dict["timestamp"] is not None:
                r_ts_raw = r_dict["timestamp"]
                if isinstance(r_ts_raw, datetime):
                    reading_ts = r_ts_raw
                elif isinstance(r_ts_raw, str):
                    try:
                        cleaned_r_ts = r_ts_raw.replace("Z", "+00:00") if r_ts_raw.endswith("Z") else r_ts_raw
                        reading_ts = datetime.fromisoformat(cleaned_r_ts)
                    except Exception:
                        reading_ts = record_ts

            if reading_ts.tzinfo is None:
                if strict:
                    raise TelemetryValidationError(
                        f"Reading {r_idx} in record {idx} has timezone-naive timestamp."
                    )
                continue

            readings_list.append(
                RawTelemetryReading(
                    channel_tag=channel_tag.strip(),
                    raw_value=numeric_val,
                    source_unit=source_unit.strip(),
                    timestamp=reading_ts,
                    sensor_id=r_dict.get("sensor_id"),
                    raw_status_flag=r_dict.get("raw_status_flag"),
                )
            )

        parsed_records.append(
            RawTelemetryRecord(
                asset_id=asset_id,
                timestamp=record_ts,
                readings=readings_list,
                metadata=rec_dict.get("metadata", {}),
            )
        )

    return RawTelemetryBatch(
        asset_id=asset_id,
        nominal_interval_seconds=nominal_interval,
        records=parsed_records,
        source_format=payload.get("source_format", "JSON"),
        ingestion_timestamp=datetime.now(timezone.utc),
    )
