"""Public short model IDs (claude-opus-4-8) ↔ internal provider model IDs."""

from __future__ import annotations

from typing import Iterable

_REGION_PREFIXES = (
    "us.",
    "eu.",
    "apac.",
    "global.",
    "jp.",
    "au.",
    "ca.",
    "us-gov.",
)

_PROVIDER_PREFIXES = (
    "anthropic.",
    "amazon.",
    "meta.",
    "mistral.",
    "cohere.",
    "nvidia.",
    "qwen.",
    "deepseek.",
)

# Short public name → preferred internal ID.
CURATED_INTERNAL: dict[str, str] = {
    "claude-opus-4-8": "us.anthropic.claude-opus-4-8",
    "claude-opus-4-7": "us.anthropic.claude-opus-4-7",
    "claude-opus-4-6": "us.anthropic.claude-opus-4-6-v1",
    "claude-opus-4-6-v1": "us.anthropic.claude-opus-4-6-v1",
    "claude-fable-5": "us.anthropic.claude-fable-5",
    "claude-sonnet-5": "us.anthropic.claude-sonnet-5",
    "claude-sonnet-4-6": "us.anthropic.claude-sonnet-4-6",
    "claude-sonnet-4-5": "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
    "claude-sonnet-4-5-20250929-v1:0": "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
    "claude-haiku-4-5": "us.anthropic.claude-haiku-4-5-20251001-v1:0",
    "claude-haiku-4-5-20251001-v1:0": "us.anthropic.claude-haiku-4-5-20251001-v1:0",
    "claude-opus-4-1": "us.anthropic.claude-opus-4-1-20250805-v1:0",
    "claude-opus-4": "us.anthropic.claude-opus-4-20250514-v1:0",
    "claude-sonnet-4": "us.anthropic.claude-sonnet-4-20250514-v1:0",
    "claude-3-7-sonnet": "us.anthropic.claude-3-7-sonnet-20250219-v1:0",
    "claude-3-7-sonnet-20250219-v1:0": "us.anthropic.claude-3-7-sonnet-20250219-v1:0",
    "claude-3-5-sonnet": "anthropic.claude-3-5-sonnet-20241022-v2:0",
    "claude-3-5-sonnet-20241022-v2:0": "anthropic.claude-3-5-sonnet-20241022-v2:0",
    "claude-3-5-haiku": "anthropic.claude-3-5-haiku-20241022-v1:0",
    "claude-3-5-haiku-20241022-v1:0": "anthropic.claude-3-5-haiku-20241022-v1:0",
    "claude-3-opus": "anthropic.claude-3-opus-20240229-v1:0",
    "claude-3-sonnet": "anthropic.claude-3-sonnet-20240229-v1:0",
    "claude-3-sonnet-20240229-v1:0": "anthropic.claude-3-sonnet-20240229-v1:0",
    "claude-3-haiku": "anthropic.claude-3-haiku-20240307-v1:0",
}

# Back-compat aliases
CURATED_BEDROCK = CURATED_INTERNAL


def is_internal_model_id(model: str) -> bool:
    """True if ID looks like a raw provider/region model id (not public short name)."""
    m = (model or "").strip().lower()
    if not m:
        return False
    if m.startswith("mrdev/"):
        return False
    if "application-inference-profile" in m:
        return True
    if any(m.startswith(p) for p in _REGION_PREFIXES):
        return True
    if any(m.startswith(p) for p in _PROVIDER_PREFIXES):
        return True
    return False


def is_public_model(model: str) -> bool:
    """True for client-facing short ids (claude-opus-4-8). Rejects provider/region ids."""
    m = (model or "").strip()
    if not m:
        return False
    if m.lower().startswith("mrdev/"):
        return False
    return not is_internal_model_id(m)


def require_public_model_id(model: str) -> str:
    """
    Validate client model id: only short public names allowed.
    Returns canonical short id (e.g. claude-fable-5). Raises ValueError otherwise.
    """
    m = (model or "").strip()
    if not m:
        raise ValueError("Model id is required")
    if m.lower().startswith("mrdev/"):
        short = to_canonical_public(m)
        raise ValueError(
            f"Unsupported model id. Use short name '{short}' "
            f"(not 'mrdev/...' or provider prefixes)."
        )
    if is_internal_model_id(m):
        short = to_canonical_public(m)
        hint = f" Use '{short}'." if short else ""
        raise ValueError(
            "Unsupported model id. Use short public names only "
            f"(e.g. claude-opus-4-8, claude-fable-5).{hint}"
        )
    return to_canonical_public(m)


def short_name(model: str) -> str:
    """Strip mrdev/, region, provider → claude-opus-4-8."""
    m = (model or "").strip()
    if not m:
        return ""
    if m.lower().startswith("mrdev/"):
        m = m[6:].strip()
    for prefix in _REGION_PREFIXES:
        if m.startswith(prefix):
            m = m[len(prefix) :]
            break
    for prefix in _PROVIDER_PREFIXES:
        if m.startswith(prefix):
            m = m[len(prefix) :]
            break
    return m


# Versioned / regional short forms → stable public IDs clients should use.
CANONICAL_PUBLIC: dict[str, str] = {
    "claude-opus-4-6-v1": "claude-opus-4-6",
    "claude-sonnet-4-5-20250929-v1:0": "claude-sonnet-4-5",
    "claude-haiku-4-5-20251001-v1:0": "claude-haiku-4-5",
    "claude-opus-4-1-20250805-v1:0": "claude-opus-4-1",
    "claude-opus-4-20250514-v1:0": "claude-opus-4",
    "claude-sonnet-4-20250514-v1:0": "claude-sonnet-4",
    "claude-3-7-sonnet-20250219-v1:0": "claude-3-7-sonnet",
    "claude-3-5-sonnet-20241022-v2:0": "claude-3-5-sonnet",
    "claude-3-5-haiku-20241022-v1:0": "claude-3-5-haiku",
    "claude-3-opus-20240229-v1:0": "claude-3-opus",
    "claude-3-sonnet-20240229-v1:0": "claude-3-sonnet",
    "claude-3-haiku-20240307-v1:0": "claude-3-haiku",
}

# Always advertised on GET /models (merged with live upstream catalog).
# Tier keys see this list filtered by ceiling (4.6 / 4.8 / fable5).
PUBLIC_CATALOG: tuple[str, ...] = (
    "claude-fable-5",
    "claude-opus-4-8",
    "claude-opus-4-7",
    "claude-opus-4-6",
    "claude-sonnet-5",
    "claude-sonnet-4-6",
    "claude-sonnet-4-5",
    "claude-haiku-4-5",
    "claude-opus-4-1",
    "claude-opus-4",
    "claude-sonnet-4",
    "claude-3-7-sonnet",
    "claude-3-5-sonnet",
    "claude-3-5-haiku",
    "claude-3-opus",
    "claude-3-sonnet",
    "claude-3-haiku",
)


def to_canonical_public(model: str) -> str:
    s = short_name(model)
    return CANONICAL_PUBLIC.get(s, s)


def to_public(model: str) -> str:
    """Any id → public short name (no prefix)."""
    return to_canonical_public(model)


def bedrock_candidates(short: str) -> list[str]:
    s = (short or "").strip()
    if not s:
        return []
    out: list[str] = []
    curated = CURATED_INTERNAL.get(s)
    if curated:
        out.append(curated)
    for mid in (
        f"us.anthropic.{s}",
        f"global.anthropic.{s}",
        f"eu.anthropic.{s}",
        f"apac.anthropic.{s}",
        f"anthropic.{s}",
        f"us.amazon.{s}",
        f"amazon.{s}",
    ):
        if mid not in out:
            out.append(mid)
    return out


def geo_failover_model_ids(model_id: str) -> list[str]:
    """Same foundation model under different CRI geo prefixes (us / eu / global / apac).

    Used when a region/account hits daily token or throttle limits so the gateway
    can retry a different geographic inference profile.
    """
    m = (model_id or "").strip()
    if not m:
        return []
    body = m
    current = ""
    for prefix in _REGION_PREFIXES:
        if m.startswith(prefix):
            current = prefix
            body = m[len(prefix) :]
            break
    # Prefer alternate geos that often have separate quotas; keep original first.
    alt_prefixes = ("us.", "eu.", "global.", "apac.", "")
    ordered = [current] if current else [""]
    for p in alt_prefixes:
        if p not in ordered:
            ordered.append(p)
    out: list[str] = []
    for p in ordered:
        cand = f"{p}{body}" if p else body
        if cand and cand not in out:
            out.append(cand)
    return out


def preferred_regions_for_model(model_id: str, all_regions: Iterable[str]) -> list[str]:
    """Order API regions so EU modelIds try EU endpoints first, etc."""
    regions = [r for r in all_regions if r]
    if not regions:
        return []
    m = (model_id or "").strip().lower()
    prefer: tuple[str, ...] = ()
    if m.startswith("eu."):
        prefer = ("eu-",)
    elif m.startswith("apac.") or m.startswith("jp.") or m.startswith("au."):
        prefer = ("ap-", "me-")
    elif m.startswith("us.") or m.startswith("us-gov."):
        prefer = ("us-",)
    elif m.startswith("ca."):
        prefer = ("ca-", "us-")
    if not prefer:
        return list(regions)
    head = [r for r in regions if any(r.startswith(p) for p in prefer)]
    tail = [r for r in regions if r not in head]
    return head + tail


def to_bedrock(model: str, available: set[str] | Iterable[str] | None = None) -> str:
    """Resolve public short name (or passthrough internal id) for invoke."""
    m = (model or "").strip()
    if not m:
        return m
    if is_internal_model_id(m):
        return m

    short = to_canonical_public(m)
    avail = set(available or [])

    curated = CURATED_INTERNAL.get(short)
    if curated and (not avail or curated in avail):
        return curated

    for cand in bedrock_candidates(short):
        if not avail or cand in avail:
            return cand

    if avail:
        ranked = sorted(
            avail,
            key=lambda x: (
                0 if x.startswith("us.") else 1 if x.startswith("global.") else 2,
                x,
            ),
        )
        for mid in ranked:
            if to_canonical_public(mid) == short:
                return mid

    cands = bedrock_candidates(short)
    return curated or (cands[0] if cands else m)


def list_public_ids(bedrock_ids: Iterable[str] | None = None) -> list[str]:
    """Unique canonical public IDs = curated catalog ∪ live upstream (deduped)."""
    seen: dict[str, None] = {}
    for mid in PUBLIC_CATALOG:
        s = to_canonical_public(mid)
        if s:
            seen.setdefault(s, None)
    for mid in bedrock_ids or []:
        s = to_canonical_public(mid)
        if s:
            seen.setdefault(s, None)

    order = list(PUBLIC_CATALOG) + list(dict.fromkeys(CURATED_INTERNAL.keys()))

    def sort_key(s: str) -> tuple:
        try:
            idx = order.index(s)
        except ValueError:
            idx = 10_000
        return (idx, s)

    return sorted(seen.keys(), key=sort_key)


def infer_tier_ceiling(allowed: Iterable[str]) -> str:
    """Map a legacy/exact allowlist to one canonical tier marker (or '' = unlimited)."""
    items = [str(m).strip() for m in allowed if str(m).strip()]
    if not items:
        return ""
    max_r = 0
    for m in items:
        max_r = max(max_r, model_tier_rank(m))
    if max_r >= 50:
        return "claude-fable-5"
    if max_r >= 40:
        return "claude-opus-4-8"
    if max_r >= 30:
        return "claude-opus-4-6"
    # Lower-only legacy lists → 4.6 ceiling (full except higher flagships).
    return "claude-opus-4-6"


def alias_set(model: str) -> set[str]:
    m = (model or "").strip()
    if not m:
        return set()
    out = {m}
    s = short_name(m)
    if s:
        out.add(s)
        out.add(f"mrdev/{s}")  # legacy clients
        out.update(bedrock_candidates(s))
    return {x for x in out if x}


# Access ceilings for API keys / CDKs (higher rank = more privileged).
# Selecting a ceiling allows every model with rank <= that ceiling.
TIER_CEILINGS: dict[str, int] = {
    "claude-opus-4-6": 30,
    "claude-opus-4-6-v1": 30,
    "claude-opus-4-8": 40,
    "claude-fable-5": 50,
}

# Known model ranks. Unlisted models rank 0 → allowed under any ceiling.
MODEL_TIER_RANK: dict[str, int] = {
    "claude-3-haiku": 5,
    "claude-3-sonnet": 5,
    "claude-3-opus": 8,
    "claude-3-5-haiku": 10,
    "claude-3-5-sonnet": 12,
    "claude-3-7-sonnet": 15,
    "claude-haiku-4-5": 16,
    "claude-haiku-4-5-20251001-v1:0": 16,
    "claude-sonnet-4": 18,
    "claude-sonnet-4-5": 20,
    "claude-sonnet-4-5-20250929-v1:0": 20,
    "claude-sonnet-4-6": 22,
    "claude-opus-4": 25,
    "claude-opus-4-1": 28,
    "claude-opus-4-6": 30,
    "claude-opus-4-6-v1": 30,
    "claude-opus-4-7": 35,
    "claude-sonnet-5": 36,
    "claude-opus-4-8": 40,
    "claude-fable-5": 50,
}

# Canonical ceilings shown in admin UI (low → high).
TIER_OPTIONS: tuple[str, ...] = (
    "claude-opus-4-6",
    "claude-opus-4-8",
    "claude-fable-5",
)


def model_tier_rank(model: str) -> int:
    s = short_name(model)
    if not s:
        return 0
    if s in MODEL_TIER_RANK:
        return MODEL_TIER_RANK[s]
    if "fable-5" in s:
        return 50
    if "opus-4-8" in s:
        return 40
    if "sonnet-5" in s and "sonnet-4" not in s:
        return 36
    if "opus-4-7" in s:
        return 35
    if "opus-4-6" in s:
        return 30
    return 0


def is_tier_ceiling(model: str) -> bool:
    return short_name(model) in TIER_CEILINGS


def allowlist_ceiling_rank(allowed: Iterable[str]) -> int | None:
    """Max ceiling rank if allowlist contains tier markers; else None (exact mode)."""
    ranks = [TIER_CEILINGS[short_name(m)] for m in allowed if is_tier_ceiling(m)]
    return max(ranks) if ranks else None


def model_allowed_by_tiers(model: str, allowed: Iterable[str]) -> bool | None:
    """
    Tier check when allowlist uses ceiling markers (4.6 / 4.8 / fable5).
    Returns None if allowlist is not tier-based (caller should exact-match).
    """
    items = [str(m).strip() for m in allowed if str(m).strip()]
    if not items:
        return True
    ceiling = allowlist_ceiling_rank(items)
    if ceiling is None:
        return None
    return model_tier_rank(model) <= ceiling


def describe_tier_allowlist(allowed: Iterable[str]) -> str | None:
    """Human label for a tier allowlist, e.g. '≤ claude-opus-4-6'."""
    items = [str(m).strip() for m in allowed if str(m).strip()]
    ceiling = allowlist_ceiling_rank(items)
    if ceiling is None:
        return None
    for name in reversed(TIER_OPTIONS):
        if TIER_CEILINGS.get(name) == ceiling:
            return name
    return None
