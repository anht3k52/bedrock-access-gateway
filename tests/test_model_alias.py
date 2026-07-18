"""Public mrdev/ model alias mapping."""

from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import pytest

from api.model_alias import (
    geo_failover_model_ids,
    list_public_ids,
    preferred_regions_for_model,
    require_public_model_id,
    to_bedrock,
    to_public,
)


def test_to_public():
    assert to_public("us.anthropic.claude-opus-4-8") == "claude-opus-4-8"
    assert to_public("mrdev/claude-opus-4-8") == "claude-opus-4-8"
    assert to_public("claude-opus-4-8") == "claude-opus-4-8"


def test_require_public_model_id_blocks_internal():
    assert require_public_model_id("claude-fable-5") == "claude-fable-5"
    assert require_public_model_id("claude-opus-4-6-v1") == "claude-opus-4-6"
    with pytest.raises(ValueError, match="short"):
        require_public_model_id("us.anthropic.claude-fable-5")
    with pytest.raises(ValueError, match="short"):
        require_public_model_id("mrdev/claude-opus-4-8")
    with pytest.raises(ValueError, match="short"):
        require_public_model_id("anthropic.claude-3-sonnet-20240229-v1:0")


def test_to_bedrock_curated():
    assert to_bedrock("claude-opus-4-8") == "us.anthropic.claude-opus-4-8"
    assert to_bedrock("claude-opus-4-6") == "us.anthropic.claude-opus-4-6-v1"
    assert to_bedrock("mrdev/claude-opus-4-8") == "us.anthropic.claude-opus-4-8"


def test_geo_failover_model_ids():
    ids = geo_failover_model_ids("us.anthropic.claude-opus-4-6-v1")
    assert ids[0] == "us.anthropic.claude-opus-4-6-v1"
    assert "eu.anthropic.claude-opus-4-6-v1" in ids
    assert "global.anthropic.claude-opus-4-6-v1" in ids
    assert "anthropic.claude-opus-4-6-v1" in ids


def test_preferred_regions_for_model():
    regions = ["us-west-2", "eu-west-1", "us-east-1", "ap-northeast-1"]
    eu = preferred_regions_for_model("eu.anthropic.claude-sonnet-4-6", regions)
    assert eu[0] == "eu-west-1"
    us = preferred_regions_for_model("us.anthropic.claude-sonnet-4-6", regions)
    assert us[0].startswith("us-")


def test_list_public_dedupes_regions():
    ids = list_public_ids(
        [
            "us.anthropic.claude-opus-4-8",
            "global.anthropic.claude-opus-4-8",
            "us.anthropic.claude-fable-5",
            "us.anthropic.claude-opus-4-6-v1",
        ]
    )
    assert ids.count("claude-opus-4-8") == 1
    assert "claude-fable-5" in ids
    assert "claude-opus-4-6" in ids
    assert "claude-opus-4-6-v1" not in ids
    # Curated catalog always present (short names)
    assert "claude-sonnet-4-5" in ids
    assert "claude-haiku-4-5" in ids
    assert "claude-3-5-sonnet" in ids
    assert "claude-opus-4" in ids
    assert len(ids) >= 12
