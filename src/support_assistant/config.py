"""Configuração central: caminhos do projeto, variáveis de ambiente e parâmetros do modelo.

Tudo que pode variar entre ambientes (provedor, modelo, chave, diretório de saída)
vem de variáveis de ambiente, opcionalmente carregadas de um arquivo `.env`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:  # python-dotenv é opcional: sem ele, só variáveis de ambiente reais são lidas.
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
PROMPTS_DIR = PROJECT_ROOT / "prompts"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "outputs"

SUPPORTED_PROVIDERS = ("fake", "gemini")
FAKE_MODEL = "fake-model-v1"
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"


class ConfigError(Exception):
    """Configuração inválida (valor de variável de ambiente fora do esperado)."""


@dataclass(frozen=True)
class Settings:
    provider: str
    model: str
    api_key: str | None
    temperature: float
    max_output_tokens: int
    timeout_seconds: float
    data_dir: Path
    prompts_dir: Path
    output_dir: Path

    @property
    def generation_config(self) -> dict:
        """Parâmetros que influenciam a saída do modelo (entram na chave de cache)."""
        return {
            "temperature": self.temperature,
            "max_output_tokens": self.max_output_tokens,
        }

    @property
    def customers_path(self) -> Path:
        return self.data_dir / "customers.json"

    @property
    def tickets_path(self) -> Path:
        return self.data_dir / "tickets.json"

    @property
    def domain_path(self) -> Path:
        return self.data_dir / "domains" / "wifi_isp.json"


def _read_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        raise ConfigError(f"{name} deve ser um número (recebido: {raw!r}). Verifique o .env.") from None


def _read_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        raise ConfigError(f"{name} deve ser um inteiro (recebido: {raw!r}). Verifique o .env.") from None


def load_settings(env_file: Path | None = None) -> Settings:
    """Lê `.env` (sem sobrescrever variáveis já definidas) e monta as configurações."""
    if load_dotenv is not None:
        load_dotenv(env_file or PROJECT_ROOT / ".env", override=False)

    provider = os.getenv("LLM_PROVIDER", "fake").strip().lower() or "fake"
    if provider not in SUPPORTED_PROVIDERS:
        raise ConfigError(
            f"LLM_PROVIDER inválido: {provider!r}. Opções: {', '.join(SUPPORTED_PROVIDERS)}. Verifique o .env."
        )

    if provider == "fake":
        model = FAKE_MODEL
        api_key = None
    else:
        model = os.getenv("LLM_MODEL", "").strip() or DEFAULT_GEMINI_MODEL
        api_key = os.getenv("GEMINI_API_KEY", "").strip() or None

    temperature = _read_float("LLM_TEMPERATURE", 0.2)
    if not 0.0 <= temperature <= 2.0:
        raise ConfigError("LLM_TEMPERATURE deve estar entre 0 e 2. Verifique o .env.")

    output_dir = Path(os.getenv("OUTPUT_DIR", "").strip() or DEFAULT_OUTPUT_DIR)

    return Settings(
        provider=provider,
        model=model,
        api_key=api_key,
        temperature=temperature,
        max_output_tokens=_read_int("LLM_MAX_OUTPUT_TOKENS", 4096),
        timeout_seconds=_read_float("LLM_TIMEOUT_SECONDS", 60.0),
        data_dir=DATA_DIR,
        prompts_dir=PROMPTS_DIR,
        output_dir=output_dir,
    )
