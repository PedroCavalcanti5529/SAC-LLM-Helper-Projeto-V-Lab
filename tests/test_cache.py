"""RN07: cache evita chamada repetida ao LLM."""

from __future__ import annotations

import json

from support_assistant.cache import make_cache_key


def test_cache_hit_avoids_second_llm_call(generator, fake_client, customer, ticket, settings):
    first = generator.generate(customer, ticket, "diagnosis", "v2")
    second = generator.generate(customer, ticket, "diagnosis", "v2")

    assert fake_client.call_count == 1, "a segunda geração idêntica não deveria chamar o LLM"
    assert first["cached"] is False
    assert second["cached"] is True
    assert second["output"] == first["output"]
    assert second["cache_key"] == first["cache_key"]

    history = json.loads((settings.output_dir / "history.json").read_text(encoding="utf-8"))
    assert [r["cached"] for r in history] == [False, True]


def test_cache_miss_when_version_changes(generator, fake_client, customer, ticket):
    generator.generate(customer, ticket, "diagnosis", "v1")
    generator.generate(customer, ticket, "diagnosis", "v2")
    assert fake_client.call_count == 2


def test_cache_key_is_order_independent():
    a = make_cache_key({"b": 1, "a": {"y": 2, "x": 3}})
    b = make_cache_key({"a": {"x": 3, "y": 2}, "b": 1})
    assert a == b
