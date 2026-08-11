"""Pure decoders for ring history-event bodies.

Each takes the event body (payload after the 4-byte timestamp) and returns a
dict, or None when the body doesn't match the documented shape. Returning None
is deliberate: a mis-decode is worse than no decode, and the raw body is always
retained for a later pass.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

EVENT_NAMES: Dict[int, str] = {
    0x41: "ring_start",
    0x42: "time_sync",
    0x43: "debug_event",
    0x44: "ibi_event",
    0x45: "state_change",
    0x46: "temp_event",
    0x47: "motion_event",
    0x48: "sleep_period_information",
    0x49: "sleep_summary_1",
    0x4A: "ppg_amplitude",
    0x4B: "sleep_phase_information",
    0x4C: "sleep_summary_2",
    0x4D: "ring_sleep_feature_information",
    0x4E: "sleep_phase_details",
    0x4F: "sleep_summary_3",
    0x50: "activity_information",
    0x51: "activity_summary_1",
    0x52: "activity_summary_2",
    0x53: "wear_event",
    0x54: "recovery_summary",
    0x55: "sleep_heart_rate",
    0x56: "alert_event",
    0x58: "sleep_summary_4",
    0x59: "eda_event",
    0x5A: "sleep_phase_data",
    0x5B: "ble_connection",
    0x5C: "user_information",
    0x5D: "hrv_event",
    0x5F: "raw_acm_event",
    0x60: "ibi_and_amplitude_event",
    0x61: "debug_data",
    0x69: "temp_period",
    0x6B: "motion_period",
    0x6C: "feature_session",
    0x6E: "spo2_ibi_and_amplitude_event",
    0x6F: "spo2_event",
    0x70: "spo2_smoothed_event",
    0x71: "green_ibi_and_amplitude_event",
    0x72: "sleep_acm_period",
    0x74: "ehr_acm_intensity_event",
    0x75: "sleep_temp_event",
    0x76: "bedtime_period",
    0x77: "spo2_dc_event",
    0x7E: "real_step_event_feature_1",
    0x7F: "real_step_event_feature_2",
    0x80: "green_ibi_quality_event",
    0x81: "cva_raw_ppg_data",
    0x8B: "spo2_r_pi_event",
}

# Beats outside this range are artefacts, not heartbeats.
PLAUSIBLE_IBI_MS = range(300, 2001)

SLEEP_PHASES = ("deep", "light", "rem", "awake")


def decode_name(tag: int) -> str:
    return EVENT_NAMES.get(tag, f"unknown_0x{tag:02x}")


def _bpm_from_ibi(intervals: List[int]) -> List[int]:
    return [60_000 // i for i in intervals if i in PLAUSIBLE_IBI_MS]


def decode_ibi_amplitude(body: bytes) -> Optional[Dict[str, Any]]:
    """0x60 — six inter-beat intervals + PPG amplitudes, bit-packed in 14 bytes."""
    if len(body) != 14:
        return None
    b = body
    ibi_ms = [
        (b[6] & 1) | (b[0] << 3) | ((b[12] >> 5) & 6),
        (b[7] & 1) | (b[1] << 3) | ((b[12] >> 3) & 6),
        (b[8] & 1) | (b[2] << 3) | ((b[12] >> 1) & 6),
        (b[9] & 1) | (b[3] << 3) | ((b[12] & 3) << 1),
        (b[10] & 1) | (b[4] << 3) | ((b[13] >> 5) & 6),
        (b[11] & 1) | (b[5] << 3) | ((b[13] >> 3) & 6),
    ]
    shift = 0 if (b[13] & 0x0F) == 7 else (b[13] & 0x0F) + 1
    amplitude = [(b[6 + k] >> 1) << shift for k in range(6)]
    return {"ibi_ms": ibi_ms, "amplitude": amplitude, "hr_bpm": _bpm_from_ibi(ibi_ms)}


def decode_green_ibi_quality(body: bytes) -> Optional[Dict[str, Any]]:
    """0x80 — green-LED IBIs with a quality flag, two bytes per sample."""
    if len(body) < 2:
        return None
    ibi_ms: List[int] = []
    quality: List[int] = []
    for i in range(0, len(body) - 1, 2):
        b0, b1 = body[i], body[i + 1]
        ibi_ms.append((b1 & 7) | (b0 << 3))
        quality.append((b1 >> 3) & 3)
    good = [ibi for ibi, q in zip(ibi_ms, quality) if q == 0]
    return {"ibi_ms": ibi_ms, "quality": quality, "hr_bpm": _bpm_from_ibi(good)}


def decode_temperatures(body: bytes) -> Optional[Dict[str, Any]]:
    """0x46/0x69/0x75 — int16 LE centi-degrees Celsius."""
    if not body or len(body) % 2:
        return None
    temps = []
    for i in range(0, len(body), 2):
        centi = int.from_bytes(body[i : i + 2], "little", signed=True)
        celsius = centi / 100.0
        if not -40.0 <= celsius <= 85.0:
            return None  # implausible: leave raw rather than mis-decode
        temps.append(round(celsius, 2))
    return {"temps_c": temps}


def decode_motion(body: bytes) -> Optional[Dict[str, Any]]:
    """0x47 — orientation, per-axis average motion, optional intensities."""
    if len(body) < 4:
        return None

    def signed(value: int) -> int:
        return (value - 256 if value > 127 else value) * 8

    out: Dict[str, Any] = {
        "orientation": body[0] >> 5,
        "motion_seconds": body[0] & 0x1F,
        "avg_x": signed(body[1]),
        "avg_y": signed(body[2]),
        "avg_z": signed(body[3]),
    }
    if len(body) >= 5:
        if body[4] & 0x40:
            return None
        out["low_intensity"] = body[4] & 0x3F
    if len(body) >= 6:
        if body[5] & 0x40:
            return None
        out["high_intensity"] = body[5] & 0x3F
    return out


def decode_hrv(body: bytes) -> Optional[Dict[str, Any]]:
    """0x5d — (avg HR bpm, avg RMSSD ms) pairs, one per 5 minutes."""
    if not body or len(body) % 2:
        return None
    return {
        "hr_bpm": list(body[0::2]),
        "rmssd_ms": list(body[1::2]),
        "interval_min": 5,
    }


def decode_spo2(body: bytes) -> Optional[Dict[str, Any]]:
    """0x6f — header byte then one SpO2 percentage per sample."""
    if len(body) < 2:
        return None
    end = len(body) - 1 if body[-1] == 0xFF else len(body)
    values = list(body[1:end])
    if not values:
        return None
    return {"spo2_percent": values}


def decode_sleep_phases(body: bytes) -> Optional[Dict[str, Any]]:
    """0x4b/0x4e/0x5a — header byte then 2-bit hypnogram codes, 4 per byte."""
    if len(body) < 2:
        return None
    phases = [
        SLEEP_PHASES[(byte >> shift) & 0x03]
        for byte in body[1:]
        for shift in (6, 4, 2, 0)
    ]
    return {"header": body[0], "phases": phases}


def decode_ascii(body: bytes) -> Optional[Dict[str, Any]]:
    text = body.decode("utf-8", errors="replace").rstrip("\x00").strip()
    return {"ascii": text} if text else None


def decode_time_sync(body: bytes) -> Optional[Dict[str, Any]]:
    if len(body) < 4:
        return None
    return {"unix_time": int.from_bytes(body[:4], "little")}


DECODERS = {
    0x42: decode_time_sync,
    0x43: decode_ascii,
    0x45: decode_ascii,
    0x46: decode_temperatures,
    0x47: decode_motion,
    0x53: decode_ascii,
    0x5D: decode_hrv,
    0x60: decode_ibi_amplitude,
    0x69: decode_temperatures,
    0x6F: decode_spo2,
    0x75: decode_temperatures,
    0x80: decode_green_ibi_quality,
    0x4B: decode_sleep_phases,
    0x4E: decode_sleep_phases,
    0x5A: decode_sleep_phases,
}


def decode_event(tag: int, body: bytes) -> Optional[Dict[str, Any]]:
    """Decode one event body, or None if there's no decoder or it doesn't fit."""
    decoder = DECODERS.get(tag)
    if decoder is None:
        return None
    try:
        return decoder(body)
    except (IndexError, ValueError):
        return None
