"""Cliente de LLM. Único módulo que faz acesso à rede.

- `FakeLLMClient`: respostas fixas e válidas por tipo de conteúdo. Não precisa de chave.
  Usado nos testes e para rodar o projeto inteiro offline (`LLM_PROVIDER=fake`).
- `GeminiClient`: Google Gemini (free tier) via REST, só com a stdlib (`urllib`).

Ambos expõem a mesma interface: `.provider`, `.model` e `.complete(system, user, content_type) -> str`.
"""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request

from support_assistant.config import Settings


class LLMError(Exception):
    """Erro base do cliente de LLM."""


class LLMConfigError(LLMError):
    """Configuração ausente/inválida (ex.: chave de API)."""


class LLMProviderError(LLMError):
    """Falha do provedor: timeout, rate limit, indisponibilidade, resposta vazia."""


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
        "ascii_diagram": "[LOS vermelho?] --sim--> visita técnica\n      |\n     não\n      v\n[Cabo ok?] --não--> reiniciar equipamentos",
        "decision_points": [
            {"id": "D1", "check": "[FAKE] LED LOS vermelho?", "if_yes": "Agendar visita técnica", "if_no": "Ir para D2"},
            {"id": "D2", "check": "[FAKE] Funciona via cabo?", "if_yes": "Problema de Wi-Fi", "if_no": "Reiniciar ONT e roteador"},
        ],
    },
}


class FakeLLMClient:
    provider = "fake"

    def __init__(self, model: str = "fake-model-v1") -> None:
        self.model = model
        self.call_count = 0  # usado nos testes para provar que o cache evitou chamadas

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

    def __init__(self, api_key: str, model: str, temperature: float, max_output_tokens: int, timeout: float) -> None:
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.max_output_tokens = max_output_tokens
        self.timeout = timeout

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
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise self._http_error(exc) from None
        except (socket.timeout, TimeoutError):
            raise LLMProviderError(
                f"O Gemini não respondeu em {self.timeout:.0f}s. Tente novamente em instantes."
            ) from None
        except urllib.error.URLError as exc:
            raise LLMProviderError(f"Sem conexão com o Gemini ({exc.reason}). Verifique sua internet.") from None
        except json.JSONDecodeError:
            raise LLMProviderError("O Gemini retornou uma resposta que não é JSON.") from None

        return self._extract_text(payload)

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
        )
    raise LLMConfigError(f"Provedor não suportado: {settings.provider!r}")
