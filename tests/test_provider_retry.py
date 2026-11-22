"""Retry por falha temporária do provedor (llm_client), separado do retry por schema.

Usa o GeminiClient com transporte HTTP simulado e espera injetada: nenhum acesso à rede e
nenhum `sleep` de verdade.
"""

from __future__ import annotations

import json
import random
import urllib.error
from email.message import Message

import pytest

from support_assistant.config import ConfigError, load_settings
from support_assistant.llm_client import (
    FAKE_RESPONSES,
    GeminiClient,
    LLMConfigError,
    LLMProviderError,
    parse_retry_after,
)

URL = "https://example.invalid/generateContent"


def http_error(code: int, retry_after: str | None = None) -> urllib.error.HTTPError:
    headers = Message()
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    return urllib.error.HTTPError(URL, code, f"HTTP {code}", headers, None)


def gemini_body(content_type: str = "diagnosis") -> bytes:
    text = json.dumps(FAKE_RESPONSES[content_type], ensure_ascii=False)
    return json.dumps({"candidates": [{"content": {"parts": [{"text": text}]}}]}).encode("utf-8")


class ScriptedTransport:
    """Transporte simulado: devolve (ou levanta) os itens do roteiro, em ordem."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = 0

    def __call__(self, request, timeout):
        self.calls += 1
        item = self.script.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


@pytest.fixture
def sleeps():
    return []


def make_client(transport, sleeps, max_retries=3):
    return GeminiClient(
        api_key="test-key",
        model="gemini-test",
        temperature=0.2,
        max_output_tokens=1024,
        timeout=5,
        max_retries=max_retries,
        backoff_base_seconds=2.0,
        transport=transport,
        sleep=sleeps.append,  # registra a espera em vez de dormir
        rng=random.Random(0),
    )


def test_503_twice_then_success(generator, customer, ticket, sleeps):
    transport = ScriptedTransport([http_error(503), http_error(503), gemini_body()])
    generator.client = make_client(transport, sleeps)

    record = generator.generate(customer, ticket, "diagnosis", "v2")

    assert transport.calls == 3
    assert record["provider_retries"] == 2
    assert record["attempts"] == 1  # retry de provedor não conta como tentativa por schema
    assert len(sleeps) == 2
    # backoff exponencial com jitter: base*2^n <= espera < base*2^n + base
    assert 2.0 <= sleeps[0] < 4.0
    assert 4.0 <= sleeps[1] < 6.0

    saved = json.loads((generator.storage.output_dir / "history.json").read_text(encoding="utf-8"))
    assert saved[-1]["provider_retries"] == 2


def test_provider_retries_not_in_cache_key(generator, customer, ticket, sleeps):
    generator.client = make_client(ScriptedTransport([http_error(503), gemini_body()]), sleeps)
    first = generator.generate(customer, ticket, "diagnosis", "v2")
    assert first["provider_retries"] == 1

    clean = ScriptedTransport([gemini_body()])
    generator.client = make_client(clean, sleeps)
    second = generator.generate(customer, ticket, "diagnosis", "v2")

    assert second["cached"] is True
    assert second["cache_key"] == first["cache_key"]
    assert second["provider_retries"] == 0
    assert clean.calls == 0


def test_429_respects_retry_after(sleeps):
    transport = ScriptedTransport([http_error(429, retry_after="7"), gemini_body()])
    client = make_client(transport, sleeps)

    client.complete("sys", "user", "diagnosis")

    assert sleeps == [7.0]
    assert client.last_provider_retries == 1


def test_429_with_very_long_retry_after_gives_up(sleeps):
    transport = ScriptedTransport([http_error(429, retry_after="3600")])
    client = make_client(transport, sleeps)
    with pytest.raises(LLMProviderError, match="rate limit"):
        client.complete("sys", "user", "diagnosis")
    assert sleeps == []
    assert transport.calls == 1


@pytest.mark.parametrize("code", [400, 401, 403, 404])
def test_client_errors_are_not_retried(code, sleeps):
    transport = ScriptedTransport([http_error(code), gemini_body()])
    client = make_client(transport, sleeps)
    with pytest.raises((LLMConfigError, LLMProviderError)):
        client.complete("sys", "user", "diagnosis")
    assert transport.calls == 1
    assert sleeps == []


def test_401_is_not_retried_and_points_to_env(sleeps):
    transport = ScriptedTransport([http_error(401)])
    client = make_client(transport, sleeps)
    with pytest.raises(LLMConfigError, match=r"\.env"):
        client.complete("sys", "user", "diagnosis")
    assert transport.calls == 1
    assert sleeps == []


def test_timeout_and_connection_errors_are_retried(sleeps):
    transport = ScriptedTransport(
        [TimeoutError(), urllib.error.URLError("conexão recusada"), ConnectionResetError(), gemini_body()]
    )
    client = make_client(transport, sleeps)
    client.complete("sys", "user", "diagnosis")
    assert client.last_provider_retries == 3


def test_exhausted_retries_friendly_error_and_persists_nothing(generator, customer, ticket, settings, sleeps):
    transport = ScriptedTransport([http_error(503)] * 4)  # 1 tentativa + 3 repetições
    generator.client = make_client(transport, sleeps, max_retries=3)

    with pytest.raises(LLMProviderError, match="Gemini indisponível no momento"):
        generator.generate(customer, ticket, "diagnosis", "v2")

    assert transport.calls == 4
    assert len(sleeps) == 3
    assert not (settings.output_dir / "history.json").exists()
    assert not (settings.output_dir / "cache.json").exists()
    assert not (settings.output_dir / "runs").exists()


def test_exhausted_retries_cli_shows_friendly_message(monkeypatch, capsys, sleeps, settings):
    from support_assistant import cli

    transport = ScriptedTransport([http_error(503)] * 4)
    monkeypatch.setattr(cli, "create_client", lambda _settings: make_client(transport, sleeps))

    code = cli.main(["generate", "-c", "c02", "-t", "t02", "-y", "diagnosis", "-p", "v2"])

    err = capsys.readouterr().err
    assert code == 1
    assert "Erro: Gemini indisponível no momento (HTTP 503)" in err
    assert "Traceback" not in err
    assert not (settings.output_dir / "history.json").exists()
    assert not (settings.output_dir / "cache.json").exists()


def test_parse_retry_after():
    assert parse_retry_after("12") == 12.0
    assert parse_retry_after("1.5") == 1.5
    assert parse_retry_after("-3") == 0.0
    assert parse_retry_after("Wed, 21 Oct 2015 07:28:00 GMT") == 0.0  # data no passado
    assert parse_retry_after("lixo") is None
    assert parse_retry_after(None) is None


@pytest.mark.parametrize(
    "name, value",
    [
        ("LLM_MAX_RETRIES", "-1"),
        ("LLM_MAX_RETRIES", "abc"),
        ("LLM_MAX_RETRIES", "99"),
        ("LLM_BACKOFF_BASE_SECONDS", "-0.5"),
        ("LLM_BACKOFF_BASE_SECONDS", "x"),
    ],
)
def test_invalid_retry_config_is_rejected(monkeypatch, tmp_path, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(ConfigError, match=name):
        load_settings(env_file=tmp_path / "nao-existe.env")


def test_retry_config_defaults(monkeypatch, tmp_path):
    monkeypatch.delenv("LLM_MAX_RETRIES", raising=False)
    monkeypatch.delenv("LLM_BACKOFF_BASE_SECONDS", raising=False)
    settings = load_settings(env_file=tmp_path / "nao-existe.env")
    assert settings.max_retries == 3
    assert settings.backoff_base_seconds == 2.0
