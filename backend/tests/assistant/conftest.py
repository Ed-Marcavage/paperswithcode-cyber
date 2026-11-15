"""The local macOS tests do not run Linux deployment process accounting."""

import importlib
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.models.database.assistant import AssistantConversation, AssistantMessage, AssistantToolCall, AssistantRun, AssistantRunStep, AssistantProviderLimit, AssistantAdmission
from backend.services.assistant_store import AssistantStore

if sys.platform != "linux":
    original_read = Path.read_text

    def local_process_stat(path, *args, **kwargs):
        if str(path) == f"/proc/{os.getpid()}/stat":
            return "1 (assistant-test) " + " ".join(["0"] * 20)
        return original_read(path, *args, **kwargs)

    # Only the import-time lifecycle singleton needs /proc. The deployed
    # runtime is Linux; keep its implementation and other file reads intact.
    with patch.object(Path, "read_text", local_process_stat):
        importlib.import_module("backend.services.deployment_lifecycle")


@pytest.fixture
def store():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")
    for model in (AssistantConversation, AssistantMessage, AssistantToolCall, AssistantRun, AssistantRunStep, AssistantProviderLimit, AssistantAdmission):
        model.__table__.create(engine)
    yield AssistantStore(sessionmaker(bind=engine, expire_on_commit=False))
    engine.dispose()


@pytest.fixture
def client(monkeypatch, store):
    from fastapi.testclient import TestClient
    from pydantic import SecretStr
    from backend.assistant_config import get_assistant_settings
    from backend.config import get_settings
    from backend.main import create_app
    from backend.services.assistant_store import get_assistant_store

    settings = get_assistant_settings()
    monkeypatch.setattr(settings, "enabled", True)
    monkeypatch.setattr(settings, "api_key", SecretStr("fake"))
    monkeypatch.setattr(settings, "base_url", "http://model.test/v1")
    monkeypatch.setattr(get_settings(), "discovery_catalog", True)
    app = create_app()
    app.dependency_overrides[get_assistant_store] = lambda: store
    return TestClient(app, headers={"Origin": "http://testserver"})


@pytest.fixture(autouse=True)
def isolate_optional_followups(monkeypatch):
    # Existing research tests isolate the original loop. Follow-up tests opt in.
    from backend.assistant_config import get_assistant_settings
    monkeypatch.setattr(get_assistant_settings(), "follow_ups_enabled", False)


@pytest.fixture(autouse=True)
def isolated_filter_cache(monkeypatch):
    from backend.services import assistant_mcp
    monkeypatch.setattr(assistant_mcp, "FILTER_CACHE", {})
    monkeypatch.setattr(assistant_mcp, "FILTER_LOCKS", {})
    monkeypatch.setattr(assistant_mcp, "TOOL_CACHE", {})
    monkeypatch.setattr(assistant_mcp, "TOOL_LOCKS", {})
