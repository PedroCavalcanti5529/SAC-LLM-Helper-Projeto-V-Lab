"""Modo público (deploy) e provedor por sessão: a chave do dono nunca é usada nem exposta."""

from __future__ import annotations

import pytest

from support_assistant.config import (
    DEFAULT_GEMINI_MODEL,
    FAKE_MODEL,
    ConfigError,
    load_settings,
    with_session_provider,
)


def test_public_mode_forces_fake_and_ignores_env_key(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_PUBLIC_MODE", "true")
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "CHAVE-DO-DONO")
    settings = load_settings(env_file=tmp_path / "nao-existe.env")
    assert settings.public_mode is True
    assert (settings.provider, settings.model, settings.api_key) == ("fake", FAKE_MODEL, None)


def test_public_mode_off_by_default(monkeypatch, tmp_path):
    monkeypatch.delenv("APP_PUBLIC_MODE", raising=False)
    assert load_settings(env_file=tmp_path / "nao-existe.env").public_mode is False


def test_invalid_public_mode_value_is_rejected(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_PUBLIC_MODE", "talvez")
    with pytest.raises(ConfigError, match="APP_PUBLIC_MODE"):
        load_settings(env_file=tmp_path / "nao-existe.env")


def test_session_provider_gemini_with_pasted_key(settings):
    session = with_session_provider(settings, "gemini", "  CHAVE-DA-SESSAO  ", "")
    assert (session.provider, session.model, session.api_key) == ("gemini", DEFAULT_GEMINI_MODEL, "CHAVE-DA-SESSAO")
    assert settings.provider == "fake" and settings.api_key is None  # original intacto (imutável)
    back = with_session_provider(session, "fake")
    assert (back.provider, back.model, back.api_key) == ("fake", FAKE_MODEL, None)


def test_session_provider_rejects_unknown_provider(settings):
    with pytest.raises(ConfigError, match="Provedor inválido"):
        with_session_provider(settings, "openai", "x")


def test_api_key_never_appears_in_repr(settings):
    session = with_session_provider(settings, "gemini", "CHAVE-SECRETA-123")
    assert "CHAVE-SECRETA-123" not in repr(session)
    assert "CHAVE-SECRETA-123" not in str(session)
