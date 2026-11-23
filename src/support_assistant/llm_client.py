"""Cliente de LLM. Único módulo que faz acesso à rede.

- `FakeLLMClient`: respostas fixas e válidas por tipo de conteúdo. Não precisa de chave.
  Usado nos testes e para rodar o projeto inteiro offline (`LLM_PROVIDER=fake`).
- `GeminiClient`: Google Gemini (free tier) via REST, só com a stdlib (`urllib`).

Ambos expõem a mesma interface: `.provider`, `.model`, `.complete(system, user, content_type) -> str`
e `.last_provider_retries` (quantas repetições por falha temporária do provedor houve na última chamada).

Retry do provedor (separado do retry por schema inválido, que fica em `generators.py`):
repete só falhas temporárias (HTTP 429, 5xx, timeout, erro de conexão), com backoff exponencial
+ jitter, respeitando o cabeçalho `Retry-After`. Nunca repete 400/401/403/404.
"""

from __future__ import annotations

import json
import logging
import random
import socket
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Callable

from support_assistant.config import Settings

logger = logging.getLogger(__name__)

# Retry-After acima disso (ex.: cota diária esgotada) não vale esperar: desiste na hora com a
# mensagem amigável, em vez de travar a CLI por minutos/horas.
MAX_RETRY_AFTER_SECONDS = 15.0


class LLMError(Exception):
    """Erro base do cliente de LLM."""


class LLMConfigError(LLMError):
    """Configuração ausente/inválida (ex.: chave de API)."""


class LLMProviderError(LLMError):
    """Falha do provedor: timeout, rate limit, indisponibilidade, resposta vazia."""


class _TransientError(Exception):
    """Uso interno: falha temporária que pode ser repetida.

    `friendly` é o erro mostrado ao usuário se as tentativas se esgotarem.
    """

    def __init__(self, friendly: LLMProviderError, reason: str, retry_after: float | None = None) -> None:
        super().__init__(reason)
        self.friendly = friendly
        self.reason = reason
        self.retry_after = retry_after


def parse_retry_after(value: str | None) -> float | None:
    """Converte o cabeçalho Retry-After (segundos ou data HTTP) em segundos. Inválido -> None."""
    if value is None or not str(value).strip():
        return None
    value = str(value).strip()
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return max(0.0, (when - datetime.now(timezone.utc)).total_seconds())


def urllib_transport(request: urllib.request.Request, timeout: float) -> bytes:
    """Transporte HTTP real. Os testes injetam um transporte simulado no lugar."""
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


# ---------------------------------------------------------------------------
# Fake
# ---------------------------------------------------------------------------

FAKE_RESPONSES: dict[str, dict] = {
    "diagnosis": {
        "hypotheses": [
            {
                "cause": "[FAKE] Interferência ou alcance insuficiente do Wi-Fi 2.4 GHz",
                "likelihood": "alta",
                "rationale": "Sintoma intermitente e dependente do cômodo (fato WIFI-01).",
            },
            {
                "cause": "[FAKE] Roteador travado após longo tempo ligado",
                "likelihood": "media",
                "rationale": "Reinício costuma resolver lentidão progressiva (fato PROC-01).",
            },
        ],
        "evidence": ["[FAKE] Cliente relata quedas frequentes no Wi-Fi."],
        "missing_info": ["[FAKE] Estado dos LEDs da ONT", "[FAKE] Se o problema ocorre também no cabo"],
        "probable_conclusion": "[FAKE] Problema local de Wi-Fi; validar LEDs e testar via cabo antes de agendar visita.",
    },
    "resolution_steps": {
        "opening": "[FAKE] Olá! Vamos resolver isso juntos.",
        "steps": [
            {"step": 1, "instruction": "[FAKE] Desligue o roteador e a ONT da tomada.", "why": "Limpa travamentos."},
            {"step": 2, "instruction": "[FAKE] Aguarde 30 segundos e ligue primeiro a ONT.", "why": None},
            {"step": 3, "instruction": "[FAKE] Quando a luz PON ficar verde fixa, ligue o roteador.", "why": None},
        ],
        "closing": "[FAKE] Se funcionar, ótimo! Qualquer coisa, estamos aqui.",
        "escalation": "[FAKE] Se o problema continuar, agendar visita técnica (fato POL-03).",
    },
    "clarifying_questions": {
        "already_known": ["[FAKE] A internet está instável"],
        "questions": [
            {"priority": 1, "question": "[FAKE] A luz LOS da ONT está vermelha?", "purpose": "Descartar falta de sinal óptico."},
            {"priority": 2, "question": "[FAKE] O problema acontece em todos os aparelhos?", "purpose": "Isolar dispositivo."},
        ],
    },
    "flow_summary": {
        "title": "[FAKE] Triagem de internet instável",
        "start": "D1",
        "nodes": [
            {
                "id": "D1",
                "question": "[FAKE] A luz LOS da ONT está vermelha?",
                "yes": {"action": "Agendar visita técnica", "ref": "ESC-01"},
                "no": {"next": "D2"},
            },
            {
                "id": "D2",
                "question": "[FAKE] Reiniciar ONT e roteador resolveu?",
                "yes": {"action": "Encerrar atendimento", "ref": None},
                "no": {"next": "D3"},
            },
            {
                "id": "D3",
                "question": "[FAKE] O problema também acontece no cabo de rede?",
                "yes": {"action": "Escalar para N2 Rede com as evidências coletadas", "ref": "ESC-02"},
                "no": {"action": "Orientar ajustes do Wi-Fi", "ref": "WIFI-01"},
            },
        ],
    },
}


class FakeLLMClient:
    provider = "fake"

    def __init__(self, model: str = "fake-model-v1") -> None:
        self.model = model
        self.call_count = 0  # usado nos testes para provar que o cache evitou chamadas
        self.last_provider_retries = 0  # o fake nunca falha

    def complete(self, system: str, user: str, content_type: str) -> str:
        self.call_count += 1
        if content_type not in FAKE_RESPONSES:
            raise LLMProviderError(f"Fake não tem resposta para {content_type!r}.")
        return json.dumps(FAKE_RESPONSES[content_type], ensure_ascii=False)


# ---------------------------------------------------------------------------
# Gemini (REST)
# ---------------------------------------------------------------------------


class GeminiClient:
    provider = "gemini"
    ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

    def __init__(
        self,
        api_key: str,
        model: str,
        temperature: float,
        max_output_tokens: int,
        timeout: float,
        max_retries: int = 3,
        backoff_base_seconds: float = 2.0,
        transport: Callable[[urllib.request.Request, float], bytes] | None = None,
        sleep: Callable[[float], None] | None = None,
        rng: random.Random | None = None,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.max_output_tokens = max_output_tokens
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_base_seconds = backoff_base_seconds
        # Injetáveis para os testes: transporte HTTP simulado e espera que não dorme de verdade.
        self.transport = transport or urllib_transport
        self.sleep = sleep or time.sleep
        self.rng = rng or random.Random()
        self.last_provider_retries = 0

    def complete(self, system: str, user: str, content_type: str) -> str:
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {
                "temperature": self.temperature,
                "maxOutputTokens": self.max_output_tokens,
                "responseMimeType": "application/json",
            },
        }
        request = urllib.request.Request(
            self.ENDPOINT.format(model=self.model),
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json", "x-goog-api-key": self.api_key},
            method="POST",
        )
        raw = self._send_with_retry(request)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise LLMProviderError("O Gemini retornou uma resposta que não é JSON.") from None
        return self._extract_text(payload)

    def _send_with_retry(self, request: urllib.request.Request) -> bytes:
        """Envia a requisição, repetindo só falhas temporárias. Conta as repetições."""
        self.last_provider_retries = 0
        attempt = 0
        while True:
            try:
                return self._send(request)
            except _TransientError as exc:
                if attempt >= self.max_retries:
                    if self.max_retries:
                        logger.warning(
                            "Provedor gemini: %s; %d repetições esgotadas, desistindo.", exc.reason, self.max_retries
                        )
                    raise exc.friendly from None
                delay = self._retry_delay(attempt, exc.retry_after)
                if delay is None:
                    logger.warning(
                        "Provedor gemini: %s com Retry-After de %.0fs (acima de %.0fs), desistindo.",
                        exc.reason, exc.retry_after, MAX_RETRY_AFTER_SECONDS,
                    )
                    raise exc.friendly from None
                attempt += 1
                logger.warning(
                    "Provedor gemini: %s (falha temporária). Repetição %d/%d em %.1fs.",
                    exc.reason, attempt, self.max_retries, delay,
                )
                self.sleep(delay)
                self.last_provider_retries = attempt

    def _retry_delay(self, attempt: int, retry_after: float | None) -> float | None:
        """Retry-After do servidor, se houver; senão backoff exponencial (base * 2^n) + jitter.

        Devolve None quando o Retry-After é longo demais para valer a espera.
        """
        if retry_after is not None:
            return None if retry_after > MAX_RETRY_AFTER_SECONDS else retry_after
        base = self.backoff_base_seconds
        return base * (2**attempt) + self.rng.uniform(0, base)

    def _send(self, request: urllib.request.Request) -> bytes:
        """Uma tentativa. Falhas temporárias viram `_TransientError`; as demais, `LLMError`."""
        try:
            return self.transport(request, self.timeout)
        except urllib.error.HTTPError as exc:
            friendly = self._http_error(exc)
            if exc.code == 429 or exc.code >= 500:
                retry_after = parse_retry_after(exc.headers.get("Retry-After") if exc.headers else None)
                raise _TransientError(friendly, f"HTTP {exc.code}", retry_after) from None
            raise friendly from None  # 400/401/403/404...: repetir não resolve
        except (socket.timeout, TimeoutError):
            raise _TransientError(
                LLMProviderError(f"O Gemini não respondeu em {self.timeout:.0f}s. Tente novamente em instantes."),
                "timeout",
            ) from None
        except urllib.error.URLError as exc:
            raise _TransientError(
                LLMProviderError(f"Sem conexão com o Gemini ({exc.reason}). Verifique sua internet."),
                f"erro de conexão ({exc.reason})",
            ) from None
        except ConnectionError as exc:  # ex.: conexão resetada / servidor fechou sem resposta
            raise _TransientError(
                LLMProviderError(f"Sem conexão com o Gemini ({exc}). Verifique sua internet."),
                f"erro de conexão ({type(exc).__name__})",
            ) from None

    def _http_error(self, exc: urllib.error.HTTPError) -> LLMError:
        try:
            detail = json.loads(exc.read().decode("utf-8")).get("error", {}).get("message", "")
        except Exception:
            detail = ""
        if exc.code == 429:
            return LLMProviderError("Limite de requisições do Gemini atingido (rate limit). Aguarde um minuto e tente de novo.")
        if exc.code in (401, 403) or "API key" in detail:
            return LLMConfigError("GEMINI_API_KEY inválida ou sem permissão. Confira o valor no arquivo .env.")
        if exc.code == 404:
            return LLMConfigError(f"Modelo {self.model!r} não encontrado no Gemini. Ajuste LLM_MODEL no .env.")
        if exc.code >= 500:
            return LLMProviderError(f"Gemini indisponível no momento (HTTP {exc.code}). Tente novamente mais tarde.")
        return LLMProviderError(f"Erro do Gemini (HTTP {exc.code}): {detail or 'sem detalhes'}")

    @staticmethod
    def _extract_text(payload: dict) -> str:
        candidates = payload.get("candidates") or []
        if not candidates:
            reason = payload.get("promptFeedback", {}).get("blockReason", "desconhecido")
            raise LLMProviderError(f"O Gemini não retornou conteúdo (motivo: {reason}).")
        candidate = candidates[0]
        parts = candidate.get("content", {}).get("parts") or []
        text = "".join(part.get("text", "") for part in parts).strip()
        if not text:
            reason = candidate.get("finishReason", "desconhecido")
            raise LLMProviderError(f"O Gemini retornou resposta vazia (finishReason: {reason}).")
        return text


def create_client(settings: Settings):
    """Fábrica: escolhe o cliente pelo `LLM_PROVIDER`."""
    if settings.provider == "fake":
        return FakeLLMClient(settings.model)
    if settings.provider == "gemini":
        if not settings.api_key:
            raise LLMConfigError(
                "GEMINI_API_KEY ausente. Copie .env.example para .env e preencha a chave "
                "(ou use LLM_PROVIDER=fake para rodar sem chave)."
            )
        return GeminiClient(
            api_key=settings.api_key,
            model=settings.model,
            temperature=settings.temperature,
            max_output_tokens=settings.max_output_tokens,
            timeout=settings.timeout_seconds,
            max_retries=settings.max_retries,
            backoff_base_seconds=settings.backoff_base_seconds,
        )
    raise LLMConfigError(f"Provedor não suportado: {settings.provider!r}")
