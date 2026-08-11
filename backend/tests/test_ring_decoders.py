"""Ring history-event decoders."""

from backend.src.ring_events import decode_event, decode_name
from backend.src.ring_events.decoders import (
    decode_green_ibi_quality,
    decode_hrv,
    decode_ibi_amplitude,
    decode_motion,
    decode_sleep_phases,
    decode_spo2,
    decode_temperatures,
)
from backend.src.ring_events.runner import rmssd


def test_event_names():
    assert decode_name(0x60) == "ibi_and_amplitude_event"
    assert decode_name(0x4B) == "sleep_phase_information"
    assert decode_name(0xF0) == "unknown_0xf0"


def test_temperatures_little_endian_centidegrees():
    # 3512 centi-°C = 35.12 °C, 3600 = 36.00 °C
    body = (3512).to_bytes(2, "little") + (3600).to_bytes(2, "little")
    assert decode_temperatures(body) == {"temps_c": [35.12, 36.0]}


def test_temperatures_reject_implausible_and_odd_length():
    assert decode_temperatures(bytes([0x00])) is None          # odd length
    assert decode_temperatures((30000).to_bytes(2, "little")) is None  # 300 °C


def test_hrv_pairs():
    decoded = decode_hrv(bytes([58, 42, 60, 39]))
    assert decoded == {"hr_bpm": [58, 60], "rmssd_ms": [42, 39], "interval_min": 5}
    assert decode_hrv(bytes([58])) is None


def test_spo2_strips_header_and_terminator():
    assert decode_spo2(bytes([0x01, 97, 96, 98, 0xFF])) == {"spo2_percent": [97, 96, 98]}
    assert decode_spo2(bytes([0x01])) is None


def test_sleep_phases_two_bit_codes():
    # 0b00_01_10_11 -> deep, light, rem, awake
    decoded = decode_sleep_phases(bytes([0x00, 0b00011011]))
    assert decoded["phases"] == ["deep", "light", "rem", "awake"]


def test_motion_signed_axes_and_intensities():
    decoded = decode_motion(bytes([0b010_00011, 0xFF, 0x01, 0x00, 0x05, 0x09]))
    assert decoded["orientation"] == 2
    assert decoded["motion_seconds"] == 3
    assert decoded["avg_x"] == -8   # 0xff = -1, ×8
    assert decoded["avg_y"] == 8
    assert decoded["low_intensity"] == 5
    assert decoded["high_intensity"] == 9


def test_motion_rejects_reserved_bit():
    assert decode_motion(bytes([0x00, 0, 0, 0, 0x40])) is None


def test_ibi_amplitude_requires_exact_length():
    assert decode_ibi_amplitude(bytes(13)) is None
    assert decode_ibi_amplitude(bytes(14)) is not None


def test_ibi_amplitude_extracts_plausible_beats():
    # b[0] << 3 = 1000 ms with the low bits clear -> 60 bpm.
    body = bytearray(14)
    body[0] = 125  # 125 << 3 = 1000
    decoded = decode_ibi_amplitude(bytes(body))
    assert decoded["ibi_ms"][0] == 1000
    assert 60 in decoded["hr_bpm"]
    assert len(decoded["amplitude"]) == 6


def test_green_ibi_quality_pairs():
    # b0=125, b1=0 -> ibi 1000 ms, quality 0 (good)
    decoded = decode_green_ibi_quality(bytes([125, 0, 100, 0b00001000]))
    assert decoded["ibi_ms"][0] == 1000
    assert decoded["quality"] == [0, 1]
    assert decoded["hr_bpm"] == [60]  # only the good-quality beat


def test_decode_event_dispatches_and_tolerates_unknown():
    assert decode_event(0x5D, bytes([58, 42]))["hr_bpm"] == [58]
    assert decode_event(0xFE, bytes([1, 2, 3])) is None
    assert decode_event(0x46, bytes([0x01])) is None  # bad shape, stays raw


def test_rmssd_from_intervals():
    # Differences of ±20 ms -> RMSSD 20
    assert rmssd([800, 820, 800, 820, 800]) == 20.0
    assert rmssd([800]) is None
    assert rmssd([50, 60]) is None  # implausible beats filtered out


def test_rmssd_ignores_artefact_jumps():
    # A missed beat creates a huge difference that must not dominate.
    clean = rmssd([800, 820, 800, 820])
    withartefact = rmssd([800, 820, 1900, 800, 820])
    assert withartefact == clean


def test_ring_reported_hrv_ignores_padding(db_session):
    """Zero slots are padding for intervals the ring didn't measure."""
    from backend.src.models import RingEventRaw
    from backend.src.ring_events.runner import ring_reported_hrv

    db_session.add(
        RingEventRaw(
            id="5d-1", tag=0x5D, timestamp=100, body="",
            decoded={"hr_bpm": [0, 64, 66], "rmssd_ms": [0, 36, 18]},
        )
    )
    db_session.commit()

    reported = ring_reported_hrv(db_session)
    assert reported["rmssd_ms"] == [36, 18]
    assert reported["average_rmssd_ms"] == 27.0
    assert reported["average_hr_bpm"] == 65
    assert reported["samples"] == 2
