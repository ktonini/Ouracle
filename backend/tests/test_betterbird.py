from __future__ import annotations

from pathlib import Path

from backend.src import betterbird


def test_discover_betterbird_uses_explicit_executable(tmp_path: Path):
    executable = tmp_path / "betterbird"
    executable.write_text("placeholder", encoding="utf-8")

    assert (
        betterbird.discover_betterbird_executable(
            {"auto_otp_betterbird_executable": str(executable)}
        )
        == executable
    )


def test_ensure_betterbird_does_not_launch_when_already_running(monkeypatch):
    monkeypatch.setattr(betterbird, "is_betterbird_running", lambda: True)

    def fail_discovery(_config):
        raise AssertionError("must not discover or launch an existing process")

    monkeypatch.setattr(betterbird, "discover_betterbird_executable", fail_discovery)
    assert betterbird.ensure_betterbird_running({}) is False


def test_ensure_betterbird_launches_configured_executable(monkeypatch, tmp_path: Path):
    executable = tmp_path / "betterbird"
    executable.write_text("placeholder", encoding="utf-8")
    launched = {}

    monkeypatch.setattr(betterbird, "is_betterbird_running", lambda: False)
    monkeypatch.setattr(
        betterbird,
        "discover_betterbird_executable",
        lambda _config: executable,
    )

    def fake_popen(command, **kwargs):
        launched["command"] = command
        launched["kwargs"] = kwargs
        return object()

    monkeypatch.setattr(betterbird.subprocess, "Popen", fake_popen)

    assert betterbird.ensure_betterbird_running({}) is True
    assert launched["command"] == [str(executable)]
    assert launched["kwargs"]["stdin"] is betterbird.subprocess.DEVNULL
