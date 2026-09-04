"""The live-model gate must reject templates and credential-shaped manifests."""

import json
from pathlib import Path

import pytest

from evals.scroll.live_manifest import LiveManifestError, validate_live_manifest


def _manifest():
    return {
        "schema_version": 1,
        "live_model": True,
        "implementation_commit": "a" * 40,
        "plan_sha256": "b" * 64,
        "credential_free_manifest_sha256": "c" * 64,
        "agent_prompt_sha256": "d" * 64,
        "provider": "mock-provider",
        "authentication_mode": "interactive-approved",
        "agent_model": "agent-model",
        "judge_model": "judge-model",
        "judge_source": "pinned-source",
        "temperature": 0,
        "seed": 1,
        "context_window_tokens": 100,
        "max_iterations": 2,
        "max_output_tokens": 25,
        "input_token_budget": 100,
        "output_token_budget": 50,
        "input_price_per_token": 0.000001,
        "output_price_per_token": 0.000002,
        "cost_ceiling_usd": 1.5,
        "source_revisions": {"source": "locked"},
        "licenses": {"source": "MIT"},
        "datasets": [{"name": "longmemeval", "revision": "abc", "item_ids": ["item-1"]}],
        "arms": {"stock": "same-settings", "scroll": "same-settings"},
    }


def test_live_manifest_requires_a_frozen_symmetric_credential_free_shape():
    validate_live_manifest(_manifest())
    validate_live_manifest({**_manifest(), "temperature": None})
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
    with pytest.raises(LiveManifestError, match="budgets"):
        validate_live_manifest({**_manifest(), "max_output_tokens": 0})


def test_live_manifest_template_is_not_live_evaluation_authorization():
    template = json.loads(Path("evals/scroll/live-manifest.template.json").read_text(encoding="utf-8"))

    with pytest.raises(LiveManifestError, match="explicitly true"):
        validate_live_manifest(template)
