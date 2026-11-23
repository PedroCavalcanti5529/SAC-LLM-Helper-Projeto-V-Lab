"""Configuração central: caminhos do projeto, variáveis de ambiente e parâmetros do modelo.

Tudo que pode variar entre ambientes (provedor, modelo, chave, diretório de saída)
vem de variáveis de ambiente, opcionalmente carregadas de um arquivo `.env`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
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
DEFAULT_GEMINI_MODEL = "gemini-3.5-flash-lite"
DEFAULT_MAX_RETRIES = 3
DEFAULT_BACKOFF_BASE_SECONDS = 2.0
MAX_RETRIES_LIMIT = 10
MAX_BACKOFF_BASE_SECONDS = 60.0


class ConfigError(Exception):
    """Configuração inválida (valor de variável de ambiente fora do esperado)."""


@dataclass(frozen=True)
class Settings:
    provider: str
    model: str
    api_key: str | None = field(repr=False)  # nunca aparece em repr/log/traceback
    temperature: float
    max_output_tokens: int
    timeout_seconds: float
    data_dir: Path
    prompts_dir: Path
    output_dir: Path
    # Retry por falha temporária do provedor (429, 5xx, timeout, conexão). Não afeta a saída,
    # por isso não entra em `generation_config` nem na chave de cache.
    max_retries: int = DEFAULT_MAX_RETRIES
    backoff_base_seconds: float = DEFAULT_BACKOFF_BASE_SECONDS
    # Deploy público (APP_PUBLIC_MODE): provedor fake por padrão, nenhuma chave lida do ambiente.
    public_mode: bool = False

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


def _read_bool(name: str) -> bool:
    raw = (os.getenv(name) or "").strip().lower()
    if raw in ("", "0", "false", "no", "nao", "não"):
        return False
    if raw in ("1", "true", "yes", "sim"):
        return True
    raise ConfigError(f"{name} deve ser true ou false (recebido: {raw!r}).")


def load_settings(env_file: Path | None = None) -> Settings:
    """Lê `.env` (sem sobrescrever variáveis já definidas) e monta as configurações."""
    if load_dotenv is not None:
        load_dotenv(env_file or PROJECT_ROOT / ".env", override=False)

    public_mode = _read_bool("APP_PUBLIC_MODE")
    provider = os.getenv("LLM_PROVIDER", "fake").strip().lower() or "fake"
    if provider not in SUPPORTED_PROVIDERS:
        raise ConfigError(
            f"LLM_PROVIDER inválido: {provider!r}. Opções: {', '.join(SUPPORTED_PROVIDERS)}. Verifique o .env."
        )

    if public_mode:
        # Deploy público: nunca usa chave do ambiente (a cota do dono não fica exposta).
        # Quem quiser o Gemini cola a própria chave na sessão (with_session_provider).
        provider, model, api_key = "fake", FAKE_MODEL, None
    elif provider == "fake":
        model = FAKE_MODEL
        api_key = None
    else:
        model = os.getenv("LLM_MODEL", "").strip() or DEFAULT_GEMINI_MODEL
        api_key = os.getenv("GEMINI_API_KEY", "").strip() or None

    temperature = _read_float("LLM_TEMPERATURE", 0.2)
    if not 0.0 <= temperature <= 2.0:
        raise ConfigError("LLM_TEMPERATURE deve estar entre 0 e 2. Verifique o .env.")

    max_retries = _read_int("LLM_MAX_RETRIES", DEFAULT_MAX_RETRIES)
    if not 0 <= max_retries <= MAX_RETRIES_LIMIT:
        raise ConfigError(f"LLM_MAX_RETRIES deve estar entre 0 e {MAX_RETRIES_LIMIT}. Verifique o .env.")

    backoff_base = _read_float("LLM_BACKOFF_BASE_SECONDS", DEFAULT_BACKOFF_BASE_SECONDS)
    if not 0.0 <= backoff_base <= MAX_BACKOFF_BASE_SECONDS:
        raise ConfigError(
            f"LLM_BACKOFF_BASE_SECONDS deve estar entre 0 e {MAX_BACKOFF_BASE_SECONDS:.0f}. Verifique o .env."
        )

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
        max_retries=max_retries,
        backoff_base_seconds=backoff_base,
        public_mode=public_mode,
    )


def with_session_provider(settings: Settings, provider: str, api_key: str | None = None, model: str | None = None) -> Settings:
    """Cópia das configurações com outro provedor, escolhido em tempo de execução (ex.: por sessão web).

    A chave recebida só vive no objeto devolvido (em memória); nada é gravado. Sem chave para o
    Gemini, `api_key` fica None e `create_client` recusa com erro claro.
    """
    provider = (provider or "").strip().lower()
    if provider not in SUPPORTED_PROVIDERS:
        raise ConfigError(f"Provedor inválido: {provider!r}. Opções: {', '.join(SUPPORTED_PROVIDERS)}.")
    if provider == "fake":
        return replace(settings, provider="fake", model=FAKE_MODEL, api_key=None)
    return replace(
        settings,
        provider=provider,
        model=(model or "").strip() or DEFAULT_GEMINI_MODEL,
        api_key=(api_key or "").strip() or None,
    )
