"""Oura API v2 ingest adapter.

Pulls data from api.ouraring.com/v2 into the shared SQLite database, replacing
the desktop Playwright export automation for server deployments. Never imports
desktop-only modules (playwright, pandas, langchain).
"""
