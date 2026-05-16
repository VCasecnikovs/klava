"""Session requests for opening Klava context in external agent UIs."""

from __future__ import annotations

import json
import shutil
import subprocess
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SESSION_REQUEST_DIR = Path.home() / ".klava" / "session-requests"
SESSION_REQUEST_INDEX = SESSION_REQUEST_DIR / "requests.jsonl"


@dataclass
class SessionRequest:
    id: str
    created_at: str
    title: str
    prompt: str
    source: str = "dashboard"
    target: str = "codex"
    cwd: str | None = None
    card_id: str | None = None
    card_type: str | None = None
    scope: str | None = None
    source_uris: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _strip_title_prefix(title: str) -> str:
    text = title.strip()
    if text.startswith("[") and "] " in text[:24]:
        return text.split("] ", 1)[1].strip()
    return text


def infer_card_type(payload: dict[str, Any]) -> str:
    explicit = _clean(payload.get("card_type") or payload.get("type")).lower()
    if explicit in {"task", "proposal", "result"}:
        return explicit
    title = _clean(payload.get("title")).upper()
    if title.startswith("[PROPOSAL]"):
        return "proposal"
    if title.startswith("[RESULT]"):
        return "result"
    return "task"


def build_prompt_from_card(payload: dict[str, Any]) -> str:
    """Build a Codex-ready prompt from a Deck card payload."""
    card_type = infer_card_type(payload)
    title = _strip_title_prefix(_clean(payload.get("title")) or "Untitled card")
    card_id = _clean(payload.get("card_id") or payload.get("id"))
    scope = _clean(payload.get("scope"))
    due = _clean(payload.get("due"))
    overdue_days = payload.get("overdue_days")
    body = _clean(payload.get("body"))
    result = _clean(payload.get("result"))
    proposal_plan = _clean(payload.get("proposal_plan"))

    due_part = f" - due {due}" if due else ""
    overdue_part = f" ({overdue_days}d overdue)" if overdue_days else ""
    scope_part = f"\n**Scope:** {scope}" if scope else ""
    id_label = "Card id" if card_type != "task" else "Task/Card id"

    if card_type == "result":
        result_body = result or body
        return "\n".join([
            "Let's discuss this Klava result in Codex.",
            "",
            f"**Result:** {title}{due_part}",
            f"**{id_label}:** {card_id or '(none)'}",
            scope_part.strip(),
            "",
            "**Result body:**",
            result_body or "(empty)",
            "",
            "Re-read the result above and wait for my questions. Do not re-run anything yet.",
        ]).replace("\n\n\n", "\n\n")

    if card_type == "proposal":
        plan = proposal_plan or body
        return "\n".join([
            "Let's walk through this Klava proposal in Codex before deciding.",
            "",
            f"**Proposal:** {title}{due_part}",
            f"**{id_label}:** {card_id or '(none)'}",
            scope_part.strip(),
            "",
            "**Plan:**",
            plan or "(empty)",
            "",
            "Read the plan above and wait for my questions. If I ask for changes, show the revised plan first. Do not execute without a clear approval.",
        ]).replace("\n\n\n", "\n\n")

    return "\n".join([
        "Let's work on this Klava task live in Codex.",
        "",
        f"**Task:** {title}{due_part}{overdue_part}",
        f"**{id_label}:** {card_id or '(none)'}",
        scope_part.strip(),
        "",
        "**Notes:**",
        body or "(empty - first give me a who / what / state / why-now briefing before planning)",
        "",
        "Start by using Klava context when relevant: Obsidian People / Organizations / Deals, vadimgest for recent messages, and existing Deck/Task state. Then give me a concise briefing and propose the next step.",
    ]).replace("\n\n\n", "\n\n")


def create_session_request(payload: dict[str, Any], cwd: str | None = None) -> SessionRequest:
    prompt = _clean(payload.get("prompt")) or build_prompt_from_card(payload)
    title = _clean(payload.get("title")) or "Klava session request"
    request = SessionRequest(
        id=f"sr_{uuid.uuid4().hex[:12]}",
        created_at=_now(),
        title=_strip_title_prefix(title),
        prompt=prompt,
        cwd=cwd,
        card_id=_clean(payload.get("card_id") or payload.get("id")) or None,
        card_type=infer_card_type(payload),
        scope=_clean(payload.get("scope")) or None,
        source_uris=[
            str(x) for x in payload.get("source_uris", [])
            if isinstance(x, str) and x.strip()
        ],
        metadata={
            k: v for k, v in payload.items()
            if k not in {"prompt", "source_uris"}
        },
    )

    SESSION_REQUEST_DIR.mkdir(parents=True, exist_ok=True)
    request_path = SESSION_REQUEST_DIR / f"{request.id}.json"
    data = asdict(request)
    request_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    with SESSION_REQUEST_INDEX.open("a", encoding="utf-8") as f:
        f.write(json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n")
    return request


def copy_prompt_to_clipboard(prompt: str) -> tuple[bool, str | None]:
    pbcopy = shutil.which("pbcopy")
    if not pbcopy:
        return False, "pbcopy not found"
    try:
        subprocess.run(
            [pbcopy],
            input=prompt,
            text=True,
            capture_output=True,
            timeout=5,
            check=True,
        )
        return True, None
    except Exception as exc:
        return False, str(exc)


def open_codex_app(cwd: str | None) -> tuple[bool, str | None]:
    codex = shutil.which("codex")
    if not codex:
        return False, "codex binary not found"
    args = [codex, "app"]
    if cwd:
        args.append(cwd)
    try:
        subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return True, None
    except Exception as exc:
        return False, str(exc)
