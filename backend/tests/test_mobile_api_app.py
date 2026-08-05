"""Mobile LAN API is read-only and must not pull in desktop automation."""

import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def mobile_api_client(monkeypatch):
    monkeypatch.setenv("OURACLE_MOBILE_API_ONLY", "1")
    monkeypatch.setenv("OURACLE_DISABLE_MOBILE_AUTOSTART", "1")
    from backend.src.mobile_api_app import create_mobile_api_app

    return TestClient(create_mobile_api_app())


def _openapi_paths(client) -> set:
    # Route objects vary across Starlette versions (included routers may be
    # wrapped and lack .path); the OpenAPI schema is a stable, complete view.
    response = client.get("/openapi.json")
    assert response.status_code == 200
    return set(response.json()["paths"])


def test_mobile_api_exposes_sync_routes(mobile_api_client):
    routes = _openapi_paths(mobile_api_client)
    assert "/api/mobile/ping" in routes
    assert "/api/mobile/sync" in routes
    assert "/api/mobile/insights/{day}" in routes


def test_mobile_api_does_not_expose_desktop_automation(mobile_api_client):
    paths = _openapi_paths(mobile_api_client)
    assert "/api/automation/status" not in paths
    assert "/api/mobile/settings" not in paths


def test_mobile_api_does_not_import_main_app():
    # Guard against regressions to the old duplicate-backend design.
    import backend.src.mobile_api_app as mobile_api_module

    source_path = mobile_api_module.__file__
    assert source_path
    with open(source_path, encoding="utf-8") as handle:
        text = handle.read()
    assert "backend.src.api.main" not in text
