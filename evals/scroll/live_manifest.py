"""Validation for a reviewed live-evaluation manifest with no credential fields."""

from __future__ import annotations

import re
from typing import Any


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_CREDENTIAL_VALUE_RE = re.compile(r"(?:^|\s)(?:basic\s+|bearer\s+|sk-|AIza|gh[pousr]_|xox[baprs]-)", re.IGNORECASE)
_MANIFEST_KEYS = frozenset({"schema_version", "live_model", "implementation_commit", "plan_sha256", "credential_free_manifest_sha256", "agent_prompt_sha256", "provider", "authentication_mode", "billing_mode", "agent_model", "judge_model", "judge_source", "temperature", "seed", "context_window_tokens", "max_iterations", "max_output_tokens", "max_parallel_workers", "input_token_budget", "output_token_budget", "cache_read_token_budget", "source_revisions", "licenses", "datasets", "arms"})
_V2_MANIFEST_KEYS = _MANIFEST_KEYS | {"context_total_ceiling_seconds"}
_V3_MANIFEST_KEYS = _V2_MANIFEST_KEYS | {"auxiliary_compression_timeout_seconds", "worker_timeout_seconds", "worker_access_token_minimum_ttl_seconds", "resume_source"}
_DATASET_KEYS = frozenset({"name", "revision", "item_ids"})
_RESUME_SOURCE_KEYS = frozenset({"manifest_sha256", "implementation_commit", "runtime_root_name", "context_total_ceiling_seconds", "auxiliary_compression_timeout_seconds", "worker_timeout_seconds", "worker_access_token_minimum_ttl_seconds"})


class LiveManifestError(ValueError):
    pass


def _require(value: Any, name: str, expected_type: type | tuple[type, ...]) -> Any:
    if not isinstance(value, expected_type) or isinstance(value, bool) or value in ("", [], {}):
        raise LiveManifestError(f"{name} is required")
    return value


def _contains_credential(value: Any) -> bool:
    if isinstance(value, dict):
        return any(
            (isinstance(key, str) and (key.lower().endswith(("token", "secret", "password", "api_key", "credential")) or key.lower() in {"authorization", "refresh"}))
            or _contains_credential(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_credential(item) for item in value)
    return isinstance(value, str) and bool(_CREDENTIAL_VALUE_RE.search(value))


def validate_live_manifest(manifest: dict[str, Any]) -> None:
    """Reject incomplete manifests before any provider or judge is contacted."""
    if _contains_credential(manifest):
        raise LiveManifestError("manifest must not contain credentials")
    schema_version = manifest.get("schema_version")
    expected_keys = _MANIFEST_KEYS if schema_version == 1 else _V2_MANIFEST_KEYS if schema_version == 2 else _V3_MANIFEST_KEYS if schema_version == 3 else None
    if expected_keys is None or set(manifest) != expected_keys:
        raise LiveManifestError("manifest must contain only the frozen schema fields")
    if isinstance(schema_version, bool):
        raise LiveManifestError("schema_version must be 1, 2, or 3")
    if manifest.get("live_model") is not True:
        raise LiveManifestError("live_model must be explicitly true")
    if not _COMMIT_RE.fullmatch(str(manifest.get("implementation_commit", ""))):
        raise LiveManifestError("implementation_commit must be a full commit SHA")
    for key in ("plan_sha256", "credential_free_manifest_sha256", "agent_prompt_sha256"):
        if not _SHA256_RE.fullmatch(str(manifest.get(key, ""))):
            raise LiveManifestError(f"{key} must be a SHA-256")
    for key in ("provider", "authentication_mode", "billing_mode", "agent_model", "judge_model", "judge_source"):
        _require(manifest.get(key), key, str)
    if manifest["provider"] != "openai-codex" or manifest["authentication_mode"] != "chatgpt-codex-oauth" or manifest["billing_mode"] != "chatgpt_subscription":
        raise LiveManifestError("live evaluation must use ChatGPT Codex OAuth subscription billing")
    if not manifest["agent_model"].startswith("gpt-") or (manifest["judge_model"] != "none-objective-verifier" and not manifest["judge_model"].startswith("gpt-")):
        raise LiveManifestError("live evaluation must use OpenAI Codex models")
    numeric_keys = ("seed", "context_window_tokens", "max_iterations", "max_output_tokens", "max_parallel_workers", "input_token_budget", "output_token_budget", "cache_read_token_budget")
    if schema_version >= 2:
        numeric_keys += ("context_total_ceiling_seconds",)
    if schema_version == 3:
        numeric_keys += ("auxiliary_compression_timeout_seconds", "worker_timeout_seconds", "worker_access_token_minimum_ttl_seconds")
    for key in numeric_keys:
        _require(manifest.get(key), key, (int, float))
    if not isinstance(manifest["max_parallel_workers"], int) or isinstance(manifest["max_parallel_workers"], bool):
        raise LiveManifestError("max_parallel_workers must be an integer")
    temperature = manifest.get("temperature")
    if temperature is not None and (not isinstance(temperature, (int, float)) or isinstance(temperature, bool) or temperature < 0):
        raise LiveManifestError("temperature must be non-negative or null when the model does not support it")
    if manifest["context_window_tokens"] <= 0 or manifest["max_iterations"] <= 0 or manifest["max_output_tokens"] <= 0 or manifest["max_parallel_workers"] <= 0 or manifest["max_parallel_workers"] > 4 or manifest["input_token_budget"] <= 0 or manifest["output_token_budget"] <= 0 or manifest["cache_read_token_budget"] <= 0 or (schema_version >= 2 and manifest["context_total_ceiling_seconds"] <= 0) or (schema_version == 3 and (manifest["auxiliary_compression_timeout_seconds"] <= 0 or manifest["worker_timeout_seconds"] <= manifest["context_total_ceiling_seconds"] or manifest["worker_access_token_minimum_ttl_seconds"] <= manifest["worker_timeout_seconds"])):
        raise LiveManifestError("token budgets must be positive and max_parallel_workers must be between 1 and 4")
    if schema_version == 3:
        resume_source = _require(manifest.get("resume_source"), "resume_source", dict)
        if set(resume_source) != _RESUME_SOURCE_KEYS or not _SHA256_RE.fullmatch(str(resume_source.get("manifest_sha256", ""))) or not _COMMIT_RE.fullmatch(str(resume_source.get("implementation_commit", ""))) or not isinstance(resume_source.get("runtime_root_name"), str) or not resume_source["runtime_root_name"]:
            raise LiveManifestError("resume_source must pin the compatible prior coding runtime")
        for key in ("context_total_ceiling_seconds", "auxiliary_compression_timeout_seconds", "worker_timeout_seconds", "worker_access_token_minimum_ttl_seconds"):
            _require(resume_source.get(key), f"resume_source.{key}", (int, float))
        if any(resume_source[key] <= 0 for key in ("context_total_ceiling_seconds", "auxiliary_compression_timeout_seconds", "worker_timeout_seconds", "worker_access_token_minimum_ttl_seconds")):
            raise LiveManifestError("resume_source timeout values must be positive")
    for key in ("source_revisions", "licenses"):
        value = _require(manifest.get(key), key, dict)
        if not all(isinstance(name, str) and name and isinstance(revision, str) and revision for name, revision in value.items()):
            raise LiveManifestError(f"{key} must be a non-empty string mapping")
    datasets = _require(manifest.get("datasets"), "datasets", list)
    if not all(isinstance(dataset, dict) and set(dataset) == _DATASET_KEYS and _require(dataset.get("name"), "dataset.name", str) and _require(dataset.get("revision"), "dataset.revision", str) and _require(dataset.get("item_ids"), "dataset.item_ids", list) and all(isinstance(item_id, str) and item_id for item_id in dataset["item_ids"]) for dataset in datasets):
        raise LiveManifestError("datasets must freeze name, revision, and item_ids")
    arms = _require(manifest.get("arms"), "arms", dict)
    if set(arms) != {"stock", "scroll"} or not all(isinstance(arm, str) and arm for arm in arms.values()) or arms["stock"] != arms["scroll"]:
        raise LiveManifestError("stock and scroll arms must use identical frozen settings")
