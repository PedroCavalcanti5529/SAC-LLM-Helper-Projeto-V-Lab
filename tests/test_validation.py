"""Validações: perfil (RN01), rubrica (RN09), retry de JSON inválido e falhas do provedor."""

from __future__ import annotations

import json

import pytest

from support_assistant.evaluation import EvaluationError, build_evaluation, validate_score
from support_assistant.generators import GenerationError
from support_assistant.llm_client import FAKE_RESPONSES, LLMProviderError
from support_assistant.models import CustomerProfile, InputValidationError


def test_profile_with_invalid_enum_fails_before_llm():
    with pytest.raises(InputValidationError, match="leigo, intermediario, avancado"):
        CustomerProfile.from_dict(
            {"id": "x", "technical_level": "expert", "communication_style": "direto", "channel": "chat"}
        )


@pytest.mark.parametrize("bad", [0, 6, "abc", "", True, 3.5])
def test_score_out_of_range_is_rejected(bad):
    with pytest.raises(EvaluationError):
        validate_score(bad)


def test_empty_justification_is_rejected():
    scores = {c: {"score": 3, "justification": "ok"} for c in ("clarity", "customer_fit", "actionability")}
    scores["clarity"]["justification"] = "   "
    with pytest.raises(EvaluationError):
        build_evaluation(scores)


class ScriptedClient:
    """Cliente que devolve respostas pré-definidas, em ordem."""

    provider = "fake"
    model = "scripted"

    def __init__(self, responses):
        self.responses = list(responses)
        self.call_count = 0

    def complete(self, system, user, content_type):
        self.call_count += 1
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def test_invalid_json_is_retried_once(generator, customer, ticket):
    valid = json.dumps(FAKE_RESPONSES["diagnosis"])
    generator.client = ScriptedClient(["isso não é json", valid])
    record = generator.generate(customer, ticket, "diagnosis", "v2")
    assert record["attempts"] == 2
    assert generator.client.call_count == 2


def test_invalid_twice_raises_and_persists_nothing(generator, customer, ticket, settings):
    generator.client = ScriptedClient(["{}", '{"hypotheses": []}'])
    with pytest.raises(GenerationError):
        generator.generate(customer, ticket, "diagnosis", "v2")
    assert not (settings.output_dir / "history.json").exists()
    assert not (settings.output_dir / "cache.json").exists()
    assert (settings.output_dir / "failures.json").exists()


def test_provider_error_persists_nothing(generator, customer, ticket, settings):
    generator.client = ScriptedClient([LLMProviderError("rate limit")])
    with pytest.raises(LLMProviderError):
        generator.generate(customer, ticket, "diagnosis", "v2")
    assert not (settings.output_dir / "history.json").exists()
    assert not (settings.output_dir / "cache.json").exists()
