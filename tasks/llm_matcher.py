"""LLM-based topic similarity for [RESULT] card dedup.

Replaces token-Jaccard with a Claude call that clusters tasks the way a
person would. Token Jaccard misses cross-language pairs, action-verb swaps,
and one-shared-entity-name false negatives — a Claude call reads the titles
and decides.

Architecture:
- One subprocess call per `create_result()` write, sending up to ~30
  candidate titles. ~5-7s on haiku, sub-1s on cache hit.
- Cache keyed by hash of (new_title + sorted candidate set), 30-min TTL.
  Heartbeat re-emits very similar inputs every cycle, so cache hit rate
  is high.
- Default-on. If `claude` CLI is missing, hits the API timeout, or returns
  garbage, we return [] and the caller falls back to token similarity.
"""

import os
import sys
import json
import time
import hashlib
import shutil
import subprocess
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

CLAUDE_CLI = shutil.which("claude") or os.path.expanduser("~/.local/bin/claude")
CACHE_DIR = Path("/tmp/klava-llm-matcher-cache")
CACHE_TTL_SECONDS = 30 * 60
DEFAULT_TIMEOUT = 45
DEFAULT_MODEL = "haiku"
MAX_CANDIDATES = 40  # cap input size; older candidates trimmed by caller

PROMPT_TEMPLATE = """You are a task-deduplication classifier. I'll show you ONE new task title and a numbered list of EXISTING task titles. Return the numbers of existing tasks that are about THE SAME TOPIC as the new task.

Same topic = same person, deal, event, system component, or issue — even if they describe different stages (draft / review / approve / send) or different actions on the same target.

Different topic = different person, different deal, different system component. A single shared word like "review" or a shared organization name on unrelated work is NOT enough. Two cards about Astrum can be different topics if they're about different PRs or features.

Output format: comma-separated numbers only, e.g. "2,5,7". If nothing matches, output the single word NONE. Output nothing else — no prose, no explanation.

NEW TASK:
{new_title}

EXISTING TASKS:
{numbered_list}

Same-topic numbers:"""


def _cache_key(new_title: str, candidates: Sequence[Tuple[str, str]]) -> str:
    h = hashlib.sha256()
    h.update(new_title.encode("utf-8"))
    for cid, ctitle in sorted(candidates):
        h.update(cid.encode("utf-8"))
        h.update(b"|")
        h.update((ctitle or "").encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()[:32]


def _load_cache(key: str) -> Optional[List[str]]:
    f = CACHE_DIR / f"{key}.json"
    if not f.exists():
        return None
    try:
        data = json.loads(f.read_text())
        if time.time() - data.get("ts", 0) > CACHE_TTL_SECONDS:
            return None
        return list(data.get("matched_ids") or [])
    except Exception:
        return None


def _save_cache(key: str, matched_ids: List[str]) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        f = CACHE_DIR / f"{key}.json"
        f.write_text(json.dumps({"ts": time.time(), "matched_ids": matched_ids}))
    except Exception as e:
        print(f"[llm_matcher] cache save failed: {e}", file=sys.stderr)


def topic_matches_llm(
    new_title: str,
    candidates: Sequence[Tuple[str, str]],
    timeout_s: int = DEFAULT_TIMEOUT,
    model: str = DEFAULT_MODEL,
) -> List[str]:
    """Return IDs of candidates whose topic matches `new_title`.

    Args:
        new_title: the title of the to-be-created RESULT card.
        candidates: (id, title) pairs to compare against.
        timeout_s: subprocess timeout for the claude CLI call.
        model: claude model alias passed to `--model`.

    Returns:
        List of matching candidate IDs (subset of input, preserves order).
        Returns `[]` on any failure — caller is expected to fall back to
        the token-Jaccard matcher.
    """
    if not new_title or not candidates:
        return []
    if len(candidates) > MAX_CANDIDATES:
        # caller should pre-trim, but enforce a hard cap to keep prompt small
        candidates = list(candidates)[-MAX_CANDIDATES:]

    if not CLAUDE_CLI or not Path(CLAUDE_CLI).exists():
        print("[llm_matcher] claude CLI not found; skipping LLM dedup",
              file=sys.stderr)
        return []

    key = _cache_key(new_title, candidates)
    cached = _load_cache(key)
    if cached is not None:
        return cached

    numbered = "\n".join(
        f"{i + 1}. {title}" for i, (_, title) in enumerate(candidates)
    )
    prompt = PROMPT_TEMPLATE.format(new_title=new_title, numbered_list=numbered)

    env = dict(os.environ)
    env.pop("CLAUDECODE", None)  # avoid nesting in active Claude Code session

    cmd = [CLAUDE_CLI, "--print", "--model", model, prompt]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            env=env,
        )
    except subprocess.TimeoutExpired:
        print(f"[llm_matcher] claude CLI timed out after {timeout_s}s",
              file=sys.stderr)
        return []
    except Exception as e:
        print(f"[llm_matcher] subprocess failed: {e}", file=sys.stderr)
        return []

    if result.returncode != 0:
        print(f"[llm_matcher] claude exit {result.returncode}: "
              f"{result.stderr[:200]}", file=sys.stderr)
        return []

    raw = (result.stdout or "").strip()
    # Normalize: take last non-empty line in case the model emitted prose.
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    if not lines:
        _save_cache(key, [])
        return []
    last = lines[-1].upper()
    if last == "NONE":
        _save_cache(key, [])
        return []

    matched_ids: List[str] = []
    for tok in lines[-1].replace(" ", ",").split(","):
        tok = tok.strip()
        if not tok or not tok.isdigit():
            continue
        idx = int(tok) - 1
        if 0 <= idx < len(candidates):
            matched_ids.append(candidates[idx][0])

    _save_cache(key, matched_ids)
    return matched_ids
