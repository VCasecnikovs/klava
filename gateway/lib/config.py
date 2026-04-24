"""Centralized config loader for the gateway.

Single source of truth for all paths, identity, integrations, and personal data.
Loads gateway/config.yaml, interpolates ${VAR} from environment, exposes typed
helpers, and supports reload (for the dashboard Settings UI).

Secret fields are marked for UI redaction via SECRET_KEYS.
"""

from __future__ import annotations

import os
import re
import threading
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

# ── Constants ─────────────────────────────────────────────────────────

DEFAULT_CONFIG_PATH = Path(
    os.environ.get(
        "CLAUDE_GATEWAY_CONFIG",
        str(Path(__file__).resolve().parent.parent / "config.yaml"),
    )
)

# Field paths that hold secrets - dashboard redacts these.
# Paths are dot-separated, e.g. "telegram.bot_token".
SECRET_KEYS = frozenset({
    "telegram.bot_token",
    "webhook.token",
    "integrations.clickhouse.primary.password",
    "integrations.clickhouse.secondary.password",
    "integrations.grafana.token",
    "integrations.telethon.api_hash",
    "integrations.telethon.session_string",
    "integrations.github.token",
    "integrations.google.oauth_client_secret",
    "integrations.obsidian.api_key",
    "integrations.gemini.api_key",
})

_ENV_RE = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)\}")
_lock = threading.Lock()
_cache: dict[str, Any] | None = None


# ── Loading ───────────────────────────────────────────────────────────

def _interpolate(value: Any) -> Any:
    """Recursively replace ${VAR} with os.environ[VAR]. Missing vars become ''."""
    if isinstance(value, str):
        return _ENV_RE.sub(lambda m: os.environ.get(m.group(1), ""), value)
    if isinstance(value, dict):
        return {k: _interpolate(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_interpolate(item) for item in value]
    return value


def load(path: Path | str | None = None, reload: bool = False) -> dict[str, Any]:
    """Load config (cached). Pass reload=True after editing the file."""
    global _cache
    with _lock:
        if _cache is not None and not reload and path is None:
            return _cache
        target = Path(path) if path else DEFAULT_CONFIG_PATH
        with open(target) as f:
            raw = yaml.safe_load(f) or {}
        _cache = _interpolate(raw)
        return _cache


def reload() -> dict[str, Any]:
    """Force reload from disk. Call after dashboard edits."""
    return load(reload=True)


# ── Path helpers ──────────────────────────────────────────────────────

def _expand(p: str) -> Path:
    return Path(os.path.expanduser(p)).resolve()


def project_root() -> Path:
    raw = load().get("paths", {}).get("project_root")
    if raw and not raw.startswith("__"):
        return _expand(raw)
    # Fallback: derive from this file's location (gateway/lib/config.py → repo root).
    return Path(__file__).resolve().parent.parent.parent


def obsidian_vault() -> Path:
    return _expand(load()["paths"]["obsidian_vault"])


def claude_cli() -> str:
    return os.path.expanduser(load()["paths"]["claude_cli"])


def node_bin() -> Path:
    return _expand(load()["paths"]["node_bin"])


def homebrew_bin() -> Path:
    return Path(load()["paths"]["homebrew_bin"])


def launch_agents_dir() -> Path:
    return _expand(load()["paths"]["launch_agents"])


# Derived paths (computed from project_root/obsidian_vault).
def claude_config_dir() -> Path:
    return project_root() / ".claude"


def settings_file() -> Path:
    return claude_config_dir() / "settings.json"


def mcp_servers_file() -> Path:
    """Return the MCP servers config file.

    Newer Claude Code versions reject mcpServers inside settings.json and
    expect a separate .mcp.json. Prefer that when present, fall back to
    settings.json for backwards compatibility with existing installs.
    """
    mcp_json = claude_config_dir() / ".mcp.json"
    if mcp_json.exists():
        return mcp_json
    return settings_file()


def plans_dir() -> Path:
    return claude_config_dir() / "plans"


def skills_dir() -> Path:
    return claude_config_dir() / "skills"


def state_dir() -> Path:
    return claude_config_dir() / "state"


def logs_dir() -> Path:
    return claude_config_dir() / "logs"


def gateway_dir() -> Path:
    return project_root() / "gateway"


def sessions_dir() -> Path:
    cfg = load().get("sessions", {})
    raw = cfg.get("dir") or str(gateway_dir() / "sessions")
    return _expand(raw)


def cron_dir() -> Path:
    return project_root() / "cron"


def cron_jobs_file() -> Path:
    raw = load().get("cron", {}).get("jobs_file")
    return _expand(raw) if raw else cron_dir() / "jobs.json"


def cron_state_file() -> Path:
    raw = load().get("cron", {}).get("state_file")
    return _expand(raw) if raw else cron_dir() / "state.json"


def cron_runs_log() -> Path:
    raw = load().get("cron", {}).get("runs_log")
    return _expand(raw) if raw else cron_dir() / "runs.jsonl"


def heartbeat_file() -> Path:
    raw = load().get("heartbeat", {}).get("heartbeat_file")
    return _expand(raw) if raw else project_root() / "HEARTBEAT.md"


def subagents_state_file() -> Path:
    raw = load().get("subagents", {}).get("state_file")
    return _expand(raw) if raw else cron_dir() / "subagents_state.json"


def self_evolve_backlog() -> Path:
    return project_root() / "self-evolve" / "backlog.md"


def views_dir() -> Path:
    sub = load().get("paths", {}).get("views_subpath", "Views")
    return obsidian_vault() / sub


def html_view_skill_dir() -> Path:
    return skills_dir() / "html-view"


def feed_log() -> Path:
    raw = load().get("paths", {}).get("feed_log")
    if raw:
        return _expand(raw)
    return home_claude_dir() / "feed" / "messages.jsonl"


def home_claude_dir() -> Path:
    raw = load().get("paths", {}).get("home_claude_dir", "~/.claude")
    return _expand(raw)


def vadimgest_state_dir() -> Path:
    raw = load().get("paths", {}).get("vadimgest_state_dir", "~/.local/share/vadimgest")
    return _expand(raw)


def vadimgest_data_dir() -> Path:
    """The project-bundled vadimgest dir (code + symlinked data)."""
    raw = vadimgest().get("data_dir") or str(project_root() / "vadimgest")
    return _expand(raw)


def heartbeat_state_file() -> Path:
    return cron_dir() / "heartbeat_state.json"


def claude_md_file() -> Path:
    return claude_config_dir() / "CLAUDE.md"


def people_dir() -> Path:
    sub = load().get("paths", {}).get("people_subpath", "People")
    return obsidian_vault() / sub


def organizations_dir() -> Path:
    sub = load().get("paths", {}).get("organizations_subpath", "Organizations")
    return obsidian_vault() / sub


def deals_dir() -> Path:
    sub = load().get("paths", {}).get("deals_subpath", "Deals")
    return obsidian_vault() / sub


def google_cli() -> str:
    # Resolution order:
    # 1. Explicit `integrations.google.cli_binary` from config (always wins).
    # 2. ~/bin/gog if the user installed gog there manually.
    # 3. shutil.which("gog") — `brew install gogcli` puts it at
    #    /opt/homebrew/bin/gog, not ~/bin/gog. Without this fallback the
    #    snapshot loader returns a non-existent path and every dashboard
    #    /api/klava/tasks request 500s with "No such file or directory".
    # 4. Bare "gog" so subprocess can produce a clean PATH error.
    import shutil
    explicit = (google().get("cli_binary") or "").strip()
    if explicit:
        return os.path.expanduser(explicit)
    home_bin = os.path.expanduser("~/bin/gog")
    if os.path.exists(home_bin):
        return home_bin
    found = shutil.which("gog")
    if found:
        return found
    return "gog"


def google_account() -> str:
    return email() or ""


# ── Identity ──────────────────────────────────────────────────────────

def identity() -> dict[str, Any]:
    return load().get("identity", {})


def user_name() -> str:
    return identity().get("user_name", "User")


def assistant_name() -> str:
    return identity().get("assistant_name", "Assistant")


def launchd_prefix() -> str:
    return identity().get("launchd_prefix", "com.vadims")


def project_slug() -> str:
    return identity().get("project_slug", "")


def github_login() -> str:
    return identity().get("github_login", "")


def email() -> str:
    return identity().get("email", "")


def timezone() -> str:
    return identity().get("timezone", "UTC")


# ── Telegram ──────────────────────────────────────────────────────────

def webhook() -> dict[str, Any]:
    return load().get("webhook", {})


def webhook_token() -> str:
    return (webhook().get("token") or "").strip()


def webhook_require_auth() -> str:
    """One of "auto" (default), "always", "never".

    "auto" means: require token-bearer auth on mutating endpoints unless
    the request comes from a loopback address (127.0.0.1, ::1). This
    keeps the dashboard friction-free for the local user while refusing
    LAN/remote clients to write state — the failure mode the API audit
    flagged for OSS release.
    """
    raw = (webhook().get("require_auth") or "auto").strip().lower()
    return raw if raw in ("auto", "always", "never") else "auto"


def telegram() -> dict[str, Any]:
    return load().get("telegram", {})


def telegram_chat_id() -> int:
    tg = telegram()
    chat = tg.get("chat_id") or 0
    if not chat:
        users = tg.get("allowed_users") or []
        chat = users[0] if users else 0
    return int(chat) if chat else 0


def telegram_topic_id(name: str) -> int | None:
    """Return the integer message_thread_id for a named TG topic.

    Reads `telegram.topics: {name: id, ...}` from config. Used by
    skills (e.g. healthcheck/observability) that route their output
    to a specific topic in the user's TG group. Returns None if the
    name isn't configured.
    """
    topics = telegram().get("topics") or {}
    val = topics.get(name)
    if val is None:
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


# ── Integrations ──────────────────────────────────────────────────────

def integrations() -> dict[str, Any]:
    return load().get("integrations", {})


def clickhouse() -> dict[str, Any]:
    return integrations().get("clickhouse", {})


def grafana() -> dict[str, Any]:
    return integrations().get("grafana", {})


def google() -> dict[str, Any]:
    return integrations().get("google", {})


def google_tasks_lists() -> dict[str, str]:
    return google().get("tasks_lists", {})


def vadimgest() -> dict[str, Any]:
    return integrations().get("vadimgest", {})


# ── Personal data ─────────────────────────────────────────────────────

def personal() -> dict[str, Any]:
    return load().get("personal", {})


def priority_deals() -> dict[str, int]:
    return personal().get("priority_deals", {})


def domain_keywords() -> dict[str, list[str]]:
    return personal().get("domain_keywords", {})


def known_people() -> list[dict[str, Any]]:
    return personal().get("known_people", [])


def github_login_map() -> dict[str, str | None]:
    return personal().get("github_login_map", {})


def github_projects() -> list[dict[str, Any]]:
    return personal().get("github_projects", [])


def task_section_order() -> dict[str, int]:
    return personal().get("task_section_order", {})


def task_section_display_order() -> list[str]:
    return personal().get("task_section_display_order", [])


def kpi_excluded_sections() -> set[str]:
    return set(personal().get("kpi_excluded_sections", []))


def billing_services() -> list[str]:
    return personal().get("billing_services", [])


def agent_git_authors() -> list[str]:
    return personal().get("agent_git_authors", [])


def default_proactive_jobs() -> set[str]:
    return set(personal().get("default_proactive_jobs", []))


def activity_skip_jobs() -> set[str]:
    return set(personal().get("activity_skip_jobs", []))


def system_jobs() -> set[str]:
    return set(personal().get("system_jobs", []))


# ── Models / timeouts ─────────────────────────────────────────────────

def default_model() -> str:
    return load().get("models", {}).get("default", "sonnet")


def context_1m_beta() -> str:
    return load().get("models", {}).get("context_1m_beta_flag", "")


def timeouts() -> dict[str, int]:
    return load().get("timeouts", {})


# ── Redaction (for dashboard Settings UI) ─────────────────────────────

def _walk(data: dict, prefix: str = "") -> list[tuple[str, Any]]:
    out: list[tuple[str, Any]] = []
    for k, v in data.items():
        path = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            out.extend(_walk(v, path))
        else:
            out.append((path, v))
    return out


def redacted() -> dict[str, Any]:
    """Return config with secret values masked. Used by GET /api/settings."""
    cfg = load()

    def _redact_value(value: Any) -> Any:
        if isinstance(value, str) and value:
            return "•" * 8
        return value

    def _walk_redact(node: Any, prefix: str = "") -> Any:
        if isinstance(node, dict):
            return {
                k: (
                    _redact_value(v)
                    if f"{prefix}.{k}".lstrip(".") in SECRET_KEYS
                    else _walk_redact(v, f"{prefix}.{k}")
                )
                for k, v in node.items()
            }
        if isinstance(node, list):
            return [_walk_redact(item, prefix) for item in node]
        return node

    return _walk_redact(cfg)


def is_secret(dotted_path: str) -> bool:
    return dotted_path in SECRET_KEYS


# ── Settings UI schema ────────────────────────────────────────────────
# Drives the dashboard Settings tab. Only fields listed here are user-
# editable - everything else (derived paths, personal data tables,
# project_slug, etc.) is hidden. Each field declares a label, type, and
# an optional description so the UI never has to render bare YAML keys.
#
# Field types: "text" | "number" | "toggle" | "select" | "secret" | "path"

_TIMEZONES = [
    "UTC", "Europe/Riga", "Europe/London", "Europe/Berlin", "Europe/Moscow",
    "America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles",
    "Asia/Tokyo", "Asia/Singapore", "Asia/Dubai", "Asia/Kolkata", "Australia/Sydney",
]

_INTERVAL_OPTIONS = [
    {"value": 15, "label": "Every 15 minutes"},
    {"value": 30, "label": "Every 30 minutes"},
    {"value": 60, "label": "Every hour"},
    {"value": 120, "label": "Every 2 hours"},
    {"value": 240, "label": "Every 4 hours"},
]

_MODEL_OPTIONS = [
    {"value": "opus", "label": "Claude Opus (best, most expensive)"},
    {"value": "sonnet", "label": "Claude Sonnet (balanced, recommended)"},
    {"value": "haiku", "label": "Claude Haiku (fast, cheap)"},
]

_STREAM_MODE_OPTIONS = [
    {"value": "draft", "label": "Draft messages while typing"},
    {"value": "spinner", "label": "Show only a spinner"},
    {"value": "off", "label": "Off - silent until done"},
]

SETTINGS_SCHEMA: list[dict[str, Any]] = [
    {
        "key": "project",
        "label": "Project",
        "description": "Where everything lives. The project folder contains code, "
                       "the cron schedule, skills, and HEARTBEAT.md. Inner paths are "
                       "derived from it automatically.",
        "fields": [
            {"path": "paths.project_root", "label": "Project folder", "type": "path",
             "description": "Where this gateway code is checked out."},
            {"path": "paths.obsidian_vault", "label": "Obsidian vault", "type": "path",
             "description": "Your Obsidian knowledge base. Required for People/Deals/Heartbeat."},
        ],
    },
    {
        "key": "you",
        "label": "You",
        "description": "Personal info baked into prompts and notifications.",
        "fields": [
            {"path": "identity.user_name", "label": "Your name", "type": "text",
             "description": "How the assistant addresses you."},
            {"path": "identity.assistant_name", "label": "Assistant name", "type": "text",
             "description": "What the assistant calls itself."},
            {"path": "identity.timezone", "label": "Timezone", "type": "select",
             "options": [{"value": tz, "label": tz} for tz in _TIMEZONES],
             "description": "Used for cron schedules and timestamps."},
            {"path": "identity.language", "label": "Default language", "type": "select",
             "options": [{"value": "en", "label": "English"},
                         {"value": "ru", "label": "Russian"}]},
        ],
    },
    {
        "key": "heartbeat",
        "label": "Heartbeat",
        "description": "Background loop that processes inbound messages on a schedule. "
                       "Reads HEARTBEAT.md from the project folder.",
        "fields": [
            {"path": "heartbeat.interval_minutes", "label": "Run", "type": "select",
             "options": _INTERVAL_OPTIONS,
             "description": "How often the heartbeat pipeline fires."},
        ],
    },
    {
        "key": "cron",
        "label": "Scheduler",
        "description": "Background job runner. Jobs and their schedules live in "
                       "cron/jobs.json inside the project folder.",
        "fields": [
            {"path": "cron.enabled", "label": "Enable scheduled jobs", "type": "toggle",
             "description": "Master switch. Off = no cron jobs run at all."},
        ],
    },
    {
        "key": "telegram",
        "label": "Telegram",
        "description": "Optional. Enables proactive notifications and a chat interface "
                       "to your bot. Leave blank to disable.",
        "fields": [
            {"path": "telegram.bot_token", "label": "Bot token", "type": "secret",
             "description": "Get one from @BotFather on Telegram."},
            {"path": "telegram.chat_id", "label": "Your chat ID", "type": "number",
             "description": "Your Telegram numeric user ID. The bot replies here."},
            {"path": "telegram.stream_mode", "label": "Streaming style", "type": "select",
             "options": _STREAM_MODE_OPTIONS},
        ],
    },
    {
        "key": "webhook",
        "label": "Dashboard server",
        "description": "Powers the dashboard you're looking at right now.",
        "fields": [
            {"path": "webhook.host", "label": "Bind host", "type": "text",
             "description": "0.0.0.0 = all network interfaces. 127.0.0.1 = local only."},
            {"path": "webhook.port", "label": "Port", "type": "number"},
            {"path": "webhook.token", "label": "Auth token", "type": "secret",
             "description": "Shared secret for mutating endpoints (POST/PATCH/DELETE)."},
            {"path": "webhook.require_auth", "label": "Require auth", "type": "select",
             "options": [
                 {"value": "auto", "label": "Auto (loopback bypass, token required from LAN)"},
                 {"value": "always", "label": "Always (token required even from localhost)"},
                 {"value": "never", "label": "Never (no token check — single-user/proxy only)"},
             ],
             "description": "Policy for /api/ mutations. GET is always open."},
        ],
    },
    {
        "key": "models",
        "label": "Models",
        "fields": [
            {"path": "models.default", "label": "Default Claude model", "type": "select",
             "options": _MODEL_OPTIONS},
            {"path": "subagents.default_model", "label": "Sub-agent model", "type": "select",
             "options": _MODEL_OPTIONS,
             "description": "Used when a parent session spawns a child agent."},
            {"path": "subagents.max_concurrent", "label": "Max concurrent sub-agents", "type": "number"},
        ],
    },
    {
        "key": "advanced",
        "label": "Advanced",
        "description": "Install-time settings. Don't touch unless you know what you're "
                       "doing - changing these can break daemons.",
        "collapsed": True,
        "fields": [
            {"path": "identity.launchd_prefix", "label": "macOS launchd label prefix", "type": "text",
             "description": "Service label prefix used for launchctl. Must match your "
                            ".plist files in ~/Library/LaunchAgents."},
            {"path": "paths.claude_cli", "label": "Claude CLI binary", "type": "path"},
            {"path": "paths.node_bin", "label": "Node.js bin directory", "type": "path"},
            {"path": "paths.homebrew_bin", "label": "Homebrew bin directory", "type": "path"},
            {"path": "identity.email", "label": "Your email", "type": "text"},
            {"path": "identity.github_login", "label": "GitHub username", "type": "text"},
        ],
    },
]


def schema() -> list[dict[str, Any]]:
    """Return the SETTINGS_SCHEMA for the dashboard UI."""
    return SETTINGS_SCHEMA
