"""Ablação v1 -> v2 -> v3: o builder monta cada versão a partir do manifesto."""

from __future__ import annotations

import json
import shutil

import pytest

from support_assistant.config import PROMPTS_DIR
from support_assistant.models import CONTENT_TYPES, InputValidationError
from support_assistant.prompt_builder import build_prompt, list_versions, load_manifest

VERSIONS = ("v1", "v2", "v3")


def _read(*parts: str) -> str:
    return PROMPTS_DIR.joinpath(*parts).read_text(encoding="utf-8").strip()


def _build(settings, customer, ticket, version, content_type="diagnosis", prompts_dir=None):
    return build_prompt(
        customer, ticket, content_type, version, prompts_dir or settings.prompts_dir, settings.domain_path
    )


def test_versions_come_from_manifests():
    assert list_versions(PROMPTS_DIR) == list(VERSIONS)


@pytest.mark.parametrize("content_type", CONTENT_TYPES)
def test_each_version_builds_a_different_prompt(settings, customer, ticket, content_type):
    prompts = [_build(settings, customer, ticket, v, content_type) for v in VERSIONS]
    assert len({p.system for p in prompts}) == 3
    assert len({p.template_hash for p in prompts}) == 3
    assert len({p.user for p in prompts}) == 1, "a camada de entrada é igual em todas as versões"


def test_v1_has_no_base_nor_domain(settings, customer, ticket):
    system = _build(settings, customer, ticket, "v1").system
    assert system == _read("v1", "role.md") + "\n\n" + _read("v1", "diagnosis.md")
    assert _read("base", "system.md") not in system
    assert "# Limites" not in system and "NetVale" not in system
    assert "Base de conhecimento" not in system


def test_v2_is_base_plus_domain_plus_v1_task(settings, customer, ticket):
    system = _build(settings, customer, ticket, "v2").system
    assert system.startswith(_read("base", "system.md"))
    assert "Base de conhecimento" in system and "NetVale" in system
    assert system.endswith(_read("v1", "diagnosis.md"))
    assert _read("v1", "role.md") not in system


def test_v3_is_base_plus_domain_plus_structured_task(settings, customer, ticket):
    system = _build(settings, customer, ticket, "v3").system
    assert system.startswith(_read("base", "system.md"))
    assert "Base de conhecimento" in system
    assert system.endswith(_read("v3", "diagnosis.md"))


def test_v2_reuses_v1_tasks_without_duplicating_files():
    assert load_manifest(PROMPTS_DIR, "v2").tasks == "v1"
    assert not list((PROMPTS_DIR / "v2").glob("*.md")), "v2 não deve ter cópia de arquivos de tarefa"


def test_layers_are_recorded(settings, customer, ticket):
    assert _build(settings, customer, ticket, "v1").layers == {
        "base": False, "domain": False, "tasks": "v1", "role": "v1/role.md"
    }
    assert _build(settings, customer, ticket, "v2").layers == {
        "base": True, "domain": True, "tasks": "v1", "role": None
    }


@pytest.fixture
def prompts_copy(tmp_path):
    target = tmp_path / "prompts"
    shutil.copytree(PROMPTS_DIR, target)
    return target


def _write_manifest(prompts_dir, version, manifest):
    (prompts_dir / version).mkdir(exist_ok=True)
    (prompts_dir / version / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def test_builder_follows_manifest_not_hardcoded_paths(settings, customer, ticket, prompts_copy):
    """Uma versão nova, só com manifesto: papel mínimo + domínio + tarefas da v3."""
    _write_manifest(
        prompts_copy, "v9", {"layers": {"base": False, "domain": True, "tasks": "v3"}, "role": "v1/role.md"}
    )
    system = _build(settings, customer, ticket, "v9", prompts_dir=prompts_copy).system
    assert system.startswith(_read("v1", "role.md"))
    assert "Base de conhecimento" in system
    assert system.endswith(_read("v3", "diagnosis.md"))
    assert _read("base", "system.md") not in system


@pytest.mark.parametrize("edited", ["v1/role.md", "base/input.md", "base/retry.md"])
def test_template_hash_covers_every_file_used(settings, customer, ticket, prompts_copy, edited):
    before = _build(settings, customer, ticket, "v1", prompts_dir=prompts_copy).template_hash
    path = prompts_copy / edited
    path.write_text(path.read_text(encoding="utf-8") + "\n(editado)", encoding="utf-8")
    after = _build(settings, customer, ticket, "v1", prompts_dir=prompts_copy).template_hash
    assert before != after


def test_template_hash_changes_with_composition(settings, customer, ticket, prompts_copy):
    """Mesmos arquivos, outra composição (sem domínio): o hash muda."""
    before = _build(settings, customer, ticket, "v2", prompts_dir=prompts_copy).template_hash
    _write_manifest(prompts_copy, "v2", {"layers": {"base": True, "domain": False, "tasks": "v1"}})
    after = _build(settings, customer, ticket, "v2", prompts_dir=prompts_copy).template_hash
    assert before != after


@pytest.mark.parametrize(
    "manifest, expected",
    [
        ({"layers": {"base": False, "domain": False, "tasks": "v1"}}, "obrigatório informar 'role'"),
        ({"layers": {"base": "sim", "domain": True, "tasks": "v1"}}, "'layers.base' deve ser true ou false"),
        ({"layers": {"base": True, "domain": True, "tasks": "nao-existe"}}, "não existe"),
        ({"layers": {"base": True, "domain": True, "tasks": "v1"}, "role": "v1/role.md"}, "remova o campo"),
    ],
)
def test_invalid_manifest_has_clear_error(prompts_copy, manifest, expected):
    _write_manifest(prompts_copy, "v9", manifest)
    with pytest.raises(InputValidationError, match=expected):
        load_manifest(prompts_copy, "v9")
