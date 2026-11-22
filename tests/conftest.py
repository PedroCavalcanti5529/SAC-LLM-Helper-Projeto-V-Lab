"""Fixtures compartilhadas. Os testes SEMPRE usam o provedor fake e um diretório temporário."""

from __future__ import annotations

import pytest

from support_assistant.cache import JsonCache
from support_assistant.config import DATA_DIR, FAKE_MODEL, PROMPTS_DIR, Settings
from support_assistant.generators import Generator
from support_assistant.llm_client import FakeLLMClient
from support_assistant.models import Ticket, load_customers
from support_assistant.storage import Storage


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        provider="fake",
        model=FAKE_MODEL,
        api_key=None,
        temperature=0.2,
        max_output_tokens=4096,
        timeout_seconds=5,
        data_dir=DATA_DIR,
        prompts_dir=PROMPTS_DIR,
        output_dir=tmp_path / "outputs",
    )


@pytest.fixture
def fake_client() -> FakeLLMClient:
    return FakeLLMClient(FAKE_MODEL)


@pytest.fixture
def generator(settings, fake_client) -> Generator:
    return Generator(
        settings=settings,
        client=fake_client,
        cache=JsonCache(settings.output_dir / "cache.json"),
        storage=Storage(settings.output_dir),
    )


@pytest.fixture
def customer(settings):
    return load_customers(settings.customers_path)["c02"]


@pytest.fixture
def ticket():
    return Ticket.from_text("O Wi-Fi cai toda noite no quarto.", "t-test")


@pytest.fixture(autouse=True)
def force_fake_provider(monkeypatch, tmp_path):
    """Garante que nenhum teste use provedor real, mesmo que exista um .env com Gemini."""
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "outputs"))
