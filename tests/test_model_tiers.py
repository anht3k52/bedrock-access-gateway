"""API key / CDK model tier ceilings."""

from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from api.db import ApiKeyRecord, model_in_allowlist
from api.model_alias import model_allowed_by_tiers, model_tier_rank


def test_tier_ranks():
    assert model_tier_rank("claude-opus-4-6") < model_tier_rank("claude-opus-4-8")
    assert model_tier_rank("claude-opus-4-8") < model_tier_rank("claude-fable-5")
    assert model_tier_rank("claude-haiku-4-5") < model_tier_rank("claude-opus-4-6")


def test_tier_46_blocks_higher():
    allowed = ["claude-opus-4-6"]
    assert model_allowed_by_tiers("claude-opus-4-6", allowed) is True
    assert model_allowed_by_tiers("claude-haiku-4-5", allowed) is True
    assert model_allowed_by_tiers("claude-sonnet-4-5", allowed) is True
    assert model_allowed_by_tiers("claude-opus-4-8", allowed) is False
    assert model_allowed_by_tiers("claude-fable-5", allowed) is False
    assert model_allowed_by_tiers("some-other-model", allowed) is True


def test_tier_48_blocks_fable():
    allowed = ["claude-opus-4-8"]
    assert model_allowed_by_tiers("claude-opus-4-6", allowed) is True
    assert model_allowed_by_tiers("claude-opus-4-8", allowed) is True
    assert model_allowed_by_tiers("claude-fable-5", allowed) is False


def test_tier_fable_allows_all():
    allowed = ["claude-fable-5"]
    assert model_allowed_by_tiers("claude-opus-4-6", allowed) is True
    assert model_allowed_by_tiers("claude-opus-4-8", allowed) is True
    assert model_allowed_by_tiers("claude-fable-5", allowed) is True


def test_api_key_record_uses_tiers():
    rec = ApiKeyRecord(
        key_id="k1",
        name="t",
        secret_hash="x",
        rpm_limit=60,
        monthly_token_quota=0,
        revoked=False,
        created_at="2026-01-01T00:00:00+00:00",
        last_used_at=None,
        usage_month="2026-01",
        prompt_tokens_month=0,
        completion_tokens_month=0,
        request_count_month=0,
        allowed_models="claude-opus-4-6",
    )
    assert rec.is_model_allowed("claude-opus-4-6")
    assert rec.is_model_allowed("us.anthropic.claude-opus-4-6-v1")
    assert not rec.is_model_allowed("claude-opus-4-8")
    assert not rec.is_model_allowed("claude-fable-5")


def test_legacy_exact_allowlist_still_works():
    assert model_in_allowlist("claude-haiku-4-5", ["claude-haiku-4-5"], tier_mode=True)
    assert not model_in_allowlist("claude-opus-4-8", ["claude-haiku-4-5"], tier_mode=True)


def test_infer_tier_from_legacy_bedrock_ids():
    from api.model_alias import infer_tier_ceiling

    assert (
        infer_tier_ceiling(["global.anthropic.claude-fable-5", "us.anthropic.claude-fable-5"])
        == "claude-fable-5"
    )
    assert (
        infer_tier_ceiling(["global.anthropic.claude-opus-4-8", "us.anthropic.claude-opus-4-8"])
        == "claude-opus-4-8"
    )
    assert (
        infer_tier_ceiling(["us.anthropic.claude-opus-4-6-v1", "us.anthropic.claude-sonnet-4-5-20250929-v1:0"])
        == "claude-opus-4-6"
    )
