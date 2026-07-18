import os
import re

API_ROUTE_PREFIX = os.environ.get("API_ROUTE_PREFIX", "/api/v1")
ADMIN_ROUTE_PREFIX = os.environ.get("ADMIN_ROUTE_PREFIX", "/admin")


def _sanitize_admin_ui_slug(raw: str) -> str:
    """SPA hash segment for admin UI — letters, digits, dash, underscore only."""
    s = (raw or "").strip().strip("/")
    s = re.sub(r"[^A-Za-z0-9_-]+", "-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-_")
    return s[:64] or "ops-console"


# Secret SPA path: https://host/#/<ADMIN_UI_SLUG>  (NOT the same as /admin API).
# Change this anytime after a leak — old bookmarks stop working.
ADMIN_UI_SLUG = _sanitize_admin_ui_slug(
    os.environ.get("ADMIN_UI_SLUG", "ops-x9k2m7q4")
)

# Optional: comma-separated IPs (or prefixes ending with *) allowed to call /admin API.
# Empty = allow any IP (auth still required). Example: 1.2.3.4,2405:4803:,113.183.
ADMIN_IP_ALLOWLIST = [
    p.strip()
    for p in os.environ.get("ADMIN_IP_ALLOWLIST", "").split(",")
    if p.strip()
]

TITLE = "MRDEV Gateway APIs"
SUMMARY = "OpenAI-Compatible RESTful APIs"
VERSION = "0.1.0"
DESCRIPTION = """
OpenAI-compatible chat and embeddings APIs.
"""

DEBUG = os.environ.get("DEBUG", "false").lower() != "false"
AWS_REGION = os.environ.get("AWS_REGION", "us-west-2")
DEFAULT_MODEL = os.environ.get("DEFAULT_MODEL", "anthropic.claude-3-sonnet-20240229-v1:0")
DEFAULT_EMBEDDING_MODEL = os.environ.get("DEFAULT_EMBEDDING_MODEL", "cohere.embed-multilingual-v3")
ENABLE_CROSS_REGION_INFERENCE = os.environ.get("ENABLE_CROSS_REGION_INFERENCE", "true").lower() != "false"
ENABLE_APPLICATION_INFERENCE_PROFILES = os.environ.get("ENABLE_APPLICATION_INFERENCE_PROFILES", "true").lower() != "false"
ENABLE_PROMPT_CACHING = os.environ.get("ENABLE_PROMPT_CACHING", "false").lower() != "false"

# On Throttling / daily quota: try other regional endpoints + geo model prefixes (us./eu./global.).
# Keep boto retries low so failover is fast instead of waiting adaptive × 8.
# Default to US regions only — EU/AP walks often add 5–20s TTFT on ValidationException.
_DEFAULT_FAILOVER_REGIONS = "us-west-2,us-east-1,us-east-2"
BEDROCK_FAILOVER_REGIONS = [
    r.strip()
    for r in os.environ.get("BEDROCK_FAILOVER_REGIONS", _DEFAULT_FAILOVER_REGIONS).split(",")
    if r.strip()
]
BEDROCK_RUNTIME_MAX_ATTEMPTS = max(1, int(os.environ.get("BEDROCK_RUNTIME_MAX_ATTEMPTS", "1")))
BEDROCK_FAILOVER_MAX_TRIES = max(1, int(os.environ.get("BEDROCK_FAILOVER_MAX_TRIES", "6")))

# Multi-key auth / quota
AUTH_DB_PATH = os.environ.get(
    "AUTH_DB_PATH",
    os.path.join(os.path.expanduser("~"), ".bedrock-access-gateway", "auth.db"),
)
ADMIN_API_KEY = os.environ.get("ADMIN_API_KEY")
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
# Prefer ADMIN_PASSWORD_SHA256 (never store plaintext in production).
# Optional ADMIN_PASSWORD_SALT: hash = sha256(f"{salt}:{password}")
# ADMIN_PASSWORD plaintext is only a fallback for local tests.
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")
ADMIN_PASSWORD_SHA256 = os.environ.get("ADMIN_PASSWORD_SHA256")
ADMIN_PASSWORD_SALT = os.environ.get("ADMIN_PASSWORD_SALT", "")
ADMIN_SESSION_HOURS = int(os.environ.get("ADMIN_SESSION_HOURS", "12"))
# If true, every process restart forces admin re-login (usually keep false).
ADMIN_REVOKE_SESSIONS_ON_STARTUP = (
    os.environ.get("ADMIN_REVOKE_SESSIONS_ON_STARTUP", "false").lower() == "true"
)
# Failed admin logins before permanent IP ban (and short lockout while counting).
ADMIN_LOGIN_MAX_FAILURES = int(os.environ.get("ADMIN_LOGIN_MAX_FAILURES", "10"))
ADMIN_LOGIN_LOCKOUT_SECONDS = int(os.environ.get("ADMIN_LOGIN_LOCKOUT_SECONDS", "900"))
# Legacy shared API_KEY bypass — keep OFF for public proxy.
ENABLE_LEGACY_API_KEY = os.environ.get("ENABLE_LEGACY_API_KEY", "false").lower() == "true"
DEFAULT_RPM_LIMIT = int(os.environ.get("DEFAULT_RPM_LIMIT", "60"))
DEFAULT_MONTHLY_TOKEN_QUOTA = int(os.environ.get("DEFAULT_MONTHLY_TOKEN_QUOTA", "2000000"))
LEGACY_KEY_ID = "legacy"
# Hide FastAPI /openapi.json unless DEBUG=true
DISABLE_OPENAPI = os.environ.get("DISABLE_OPENAPI", "true").lower() != "false"
