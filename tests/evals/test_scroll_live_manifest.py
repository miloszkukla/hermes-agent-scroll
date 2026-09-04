"""The live-model gate must reject templates and credential-shaped manifests."""

import json
from pathlib import Path

import pytest

from evals.scroll.coding_live import run_coding_evaluation
from evals.scroll.hermes_live import LiveRunError, run_live_evaluation
from evals.scroll.live_manifest import LiveManifestError, validate_live_manifest


def _manifest():
    return {
        "schema_version": 1,
        "live_model": True,
        "implementation_commit": "a" * 40,
        "plan_sha256": "b" * 64,
        "credential_free_manifest_sha256": "c" * 64,
        "agent_prompt_sha256": "d" * 64,
        "provider": "openai-codex",
        "authentication_mode": "chatgpt-codex-oauth",
        "billing_mode": "chatgpt_subscription",
        "agent_model": "gpt-5.6-luna",
        "judge_model": "gpt-5.6-luna",
        "judge_source": "pinned-source",
        "temperature": 0,
        "seed": 1,
        "context_window_tokens": 100,
        "max_iterations": 2,
        "max_output_tokens": 25,
        "max_parallel_workers": 2,
        "input_token_budget": 100,
        "output_token_budget": 50,
        "cache_read_token_budget": 100,
        "source_revisions": {"source": "locked"},
        "licenses": {"source": "MIT"},
        "datasets": [{"name": "longmemeval", "revision": "abc", "item_ids": ["item-1"]}],
        "arms": {"stock": "same-settings", "scroll": "same-settings"},
    }


def _coding_manifest():
    return {**_manifest(), "schema_version": 3, "context_total_ceiling_seconds": 1500, "auxiliary_compression_timeout_seconds": 400, "worker_timeout_seconds": 1650, "worker_access_token_minimum_ttl_seconds": 1800, "resume_attestation_sha256": "a" * 64, "resume_source": {"manifest_sha256": "e" * 64, "implementation_commit": "f" * 40, "runtime_root_name": "live-coding-gated-20260904-r4", "context_total_ceiling_seconds": 900, "auxiliary_compression_timeout_seconds": 300, "worker_timeout_seconds": 1200, "worker_access_token_minimum_ttl_seconds": 1260}}


def test_live_manifest_requires_a_frozen_symmetric_credential_free_shape():
    validate_live_manifest(_manifest())
    validate_live_manifest({**_manifest(), "temperature": None})
    validate_live_manifest({**_manifest(), "schema_version": 2, "context_total_ceiling_seconds": 900})
    validate_live_manifest(_coding_manifest())
    with pytest.raises(LiveManifestError, match="identical"):
        validate_live_manifest({**_manifest(), "arms": {"stock": "a", "scroll": "b"}})
    with pytest.raises(LiveManifestError, match="credentials"):
        validate_live_manifest({**_manifest(), "api_key": "forbidden"})
    nested_credential = _manifest()
    nested_credential["datasets"][0]["api_key"] = "forbidden"
    with pytest.raises(LiveManifestError, match="credentials"):
        validate_live_manifest(nested_credential)
    nested_value = _manifest()
    nested_value["arms"]["stock"] = "Bearer forbidden"
    nested_value["arms"]["scroll"] = "Bearer forbidden"
    with pytest.raises(LiveManifestError, match="credentials"):
        validate_live_manifest(nested_value)
    for key, value in (("authorization", "Basic forbidden"), ("refresh", "forbidden")):
        nested_credential = _manifest()
        nested_credential["datasets"][0][key] = value
        with pytest.raises(LiveManifestError, match="credentials"):
            validate_live_manifest(nested_credential)
    with pytest.raises(LiveManifestError, match="temperature"):
        validate_live_manifest({**_manifest(), "temperature": True})
    with pytest.raises(LiveManifestError, match="ChatGPT Codex"):
        validate_live_manifest({**_manifest(), "provider": "openrouter"})
    with pytest.raises(LiveManifestError, match="integer"):
        validate_live_manifest({**_manifest(), "max_parallel_workers": 1.5})
    with pytest.raises(LiveManifestError, match="budgets"):
        validate_live_manifest({**_manifest(), "max_output_tokens": 0})
    with pytest.raises(LiveManifestError, match="budgets"):
        validate_live_manifest({**_manifest(), "cache_read_token_budget": 0})
    with pytest.raises(LiveManifestError, match="budgets"):
        validate_live_manifest({**_manifest(), "schema_version": 2, "context_total_ceiling_seconds": 0})
    with pytest.raises(LiveManifestError, match="budgets"):
        validate_live_manifest({**_coding_manifest(), "worker_timeout_seconds": 1500})


def test_live_manifest_template_is_not_live_evaluation_authorization():
    template = json.loads(Path("evals/scroll/live-manifest.template.json").read_text(encoding="utf-8"))

    with pytest.raises(LiveManifestError, match="explicitly true"):
        validate_live_manifest(template)


def test_live_evaluators_bind_their_manifest_schema_before_provenance_or_auth(tmp_path):
    coding = _manifest()
    coding_path = tmp_path / "coding.json"
    coding_path.write_text(json.dumps(coding), encoding="utf-8")

    with pytest.raises(LiveRunError, match="coding evaluation requires schema_version 3"):
        run_coding_evaluation(coding_path, runtime_root=tmp_path / "coding-runtime", output_path=tmp_path / "coding-report.json")

    memory = {**_manifest(), "schema_version": 2, "context_total_ceiling_seconds": 900}
    memory_path = tmp_path / "memory.json"
    memory_path.write_text(json.dumps(memory), encoding="utf-8")

    with pytest.raises(LiveRunError, match="memory evaluation requires schema_version 1"):
        run_live_evaluation(memory_path, longmemeval_path=tmp_path / "longmemeval.json", beam_chats_root=tmp_path / "beam", scroll_source=tmp_path / "scroll", runtime_root=tmp_path / "memory-runtime", output_path=tmp_path / "memory-report.json")
