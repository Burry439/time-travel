"""Every test runs with AI_MODE=stub: a test must never make a real (paid) model call, even when
backend/.env holds keys. Tests that need a model's answer script it with monkeypatch."""

import pytest


@pytest.fixture(autouse=True)
def no_real_models(monkeypatch):
    monkeypatch.setenv("AI_MODE", "stub")
