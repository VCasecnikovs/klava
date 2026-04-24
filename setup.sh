#!/bin/bash
# Claude Agent System - Setup Script
# Run once after cloning: ./setup.sh
#
# Templating: LaunchAgent plists and cron/jobs.json.example are checked in
# with __HOME__, __REPO_DIR__, __PYTHON_BIN__, __PYTHON_DIR__,
# __OBSIDIAN_VAULT__ placeholders. setup.sh substitutes them so the repo works
# from any clone location and any Python install without committing
# machine-specific paths. __OBSIDIAN_VAULT__ is pulled from
# gateway/config.yaml (paths.obsidian_vault), falling back to
# ~/Documents/MyBrain.
#
# Plists ship as com.vadims.*.plist (brand prefix). If the user sets
# identity.launchd_prefix in config.yaml, filenames and Label keys are
# rewritten on install.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
CLAUDE_DIR="$REPO_DIR/.claude"

# Ensure git submodules are initialized before anything else. vadimgest lives as
# a submodule; if it's missing, the plist still renders and launchd crash-loops
# with "No module named vadimgest" (see /tmp/vadimgest-dashboard.log).
if [ -d "$REPO_DIR/.git" ] || [ -f "$REPO_DIR/.git" ]; then
    if [ -f "$REPO_DIR/.gitmodules" ]; then
        echo "[0/8] Initializing git submodules..."
        SUBMODULE_LOG="$(mktemp -t klava-submodule.XXXXXX)"

        # `--force` heals a half-initialized state from a previous failed run
        # (empty worktree but cached .git/modules/<name>, or user manually
        # `rm -rf`'d the worktree to retry). Without --force, git sees the
        # cached metadata and treats the update as a no-op, leaving the
        # worktree empty and the rest of setup.sh dying six steps later.
        if ! git -C "$REPO_DIR" submodule update --init --recursive --force 2>&1 | tee "$SUBMODULE_LOG"; then
            echo "" >&2
            echo "ERROR: git submodule update failed." >&2
            if grep -qE "Repository not found|could not read Username|Authentication failed" "$SUBMODULE_LOG"; then
                echo "" >&2
                echo "The vadimgest submodule is PRIVATE. You need GitHub auth + collaborator access." >&2
                echo "" >&2
                echo "  1. Make sure Vadim added your GitHub handle as a collaborator on" >&2
                echo "     github.com/VCasecnikovs/vadimgest (ask him if unsure)." >&2
                echo "  2. Authenticate git for HTTPS:" >&2
                echo "       gh auth login                # if not already signed in" >&2
                echo "       gh auth setup-git            # configures git credential helper" >&2
                echo "     Or configure a PAT in ~/.netrc / git credential manager." >&2
                echo "  3. Re-run ./setup.sh" >&2
            else
                echo "       Fix network/auth, then re-run ./setup.sh." >&2
            fi
            rm -f "$SUBMODULE_LOG"
            exit 1
        fi
        rm -f "$SUBMODULE_LOG"

        # Verify each submodule's worktree is actually populated. git's
        # "checked out <sha>" message is not a guarantee — a stale
        # .git/modules cache plus an empty worktree leaves status at
        # "-<sha>" (uninitialized) but the update still exits 0. Catch that
        # here so step 7 doesn't die later with a misleading error.
        SUB_STATUS="$(git -C "$REPO_DIR" submodule status --recursive)"
        if printf '%s\n' "$SUB_STATUS" | grep -qE '^-'; then
            echo "" >&2
            echo "ERROR: submodule update reported success but at least one submodule" >&2
            echo "       is still uninitialized (leading '-' in status):" >&2
            printf '%s\n' "$SUB_STATUS" | grep -E '^-' | sed 's/^/         /' >&2
            echo "" >&2
            echo "       This usually means a previous run left .git/modules/<name>" >&2
            echo "       in a half-broken state. Reset and retry:" >&2
            echo "         git -C \"$REPO_DIR\" submodule deinit -f --all" >&2
            echo "         rm -rf \"$REPO_DIR/.git/modules\"" >&2
            echo "         rm -rf \"$REPO_DIR/vadimgest\"" >&2
            echo "         ./setup.sh" >&2
            exit 1
        fi

        # Belt-and-suspenders: the rest of setup.sh assumes vadimgest's
        # pyproject.toml is on disk. Check now, not at step 7.
        if [ ! -f "$REPO_DIR/vadimgest/pyproject.toml" ]; then
            echo "" >&2
            echo "ERROR: vadimgest/pyproject.toml missing despite a clean submodule status." >&2
            echo "       Worktree contents:" >&2
            ls -la "$REPO_DIR/vadimgest" 2>&1 | sed 's/^/         /' >&2
            echo "       Submodule status:" >&2
            printf '%s\n' "$SUB_STATUS" | sed 's/^/         /' >&2
            exit 1
        fi
    fi
fi

# Detect Python: honor $PYTHON if set. Otherwise prefer a pyenv-managed CPython
# (no PEP 668 lock, matches the user's existing install) before falling back to
# whatever python3 is first on PATH (often Homebrew, which blocks pip installs).
find_brew() {
    # Returns path to brew on stdout, exits 1 if not found. brew may not be
    # on PATH in fresh non-login shells (common on macOS Sequoia).
    if command -v brew >/dev/null 2>&1; then
        command -v brew
    elif [ -x /opt/homebrew/bin/brew ]; then
        echo /opt/homebrew/bin/brew
    elif [ -x /usr/local/bin/brew ]; then
        echo /usr/local/bin/brew
    else
        return 1
    fi
}

ensure_brew() {
    # Ensure Homebrew is installed. On first run without brew, auto-runs the
    # official install script in non-interactive mode. Prints the brew path
    # on stdout so callers can capture it.
    if find_brew; then
        return 0
    fi
    echo "" >&2
    echo "  Homebrew not found — installing (requires your macOS password for sudo)..." >&2
    echo "  Script: https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh" >&2
    echo "" >&2
    if ! NONINTERACTIVE=1 /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)" >/tmp/klava-brew-install.log 2>&1; then
        echo "ERROR: Homebrew install failed — see /tmp/klava-brew-install.log" >&2
        tail -n 30 /tmp/klava-brew-install.log >&2 || true
        exit 1
    fi
    echo "  ✓ Homebrew installed" >&2
    if ! find_brew; then
        echo "ERROR: Homebrew reported success but 'brew' still not found." >&2
        exit 1
    fi
}

detect_python() {
    # Pick the best python3 available. Preference order:
    # 1. $PYTHON env override (explicit)
    # 2. pyenv (user already manages versions)
    # 3. Brew versioned python3.13 / 3.12 / 3.11 — these have full wheel
    #    coverage for our dep tree (cryptography, pynacl, etc.). 3.14 is
    #    intentionally LAST: as of late 2026 many of our transitive deps
    #    don't ship 3.14 wheels yet, so pip falls back to source builds
    #    that need Rust + cc and silently fail mid-install.
    # 4. command -v python3 (Apple's 3.9 ends up here on macOS — too old)
    PYTHON_BIN=""
    if [ -n "${PYTHON:-}" ]; then
        PYTHON_BIN="$PYTHON"
    elif [ -x "$HOME/.pyenv/shims/python3" ] && [ -n "$(ls "$HOME/.pyenv/versions" 2>/dev/null)" ]; then
        # Resolve shim to the concrete versioned binary so launchd plists
        # point at a stable path (shims depend on cwd + .python-version).
        # Prefer the latest 3.13.x; fall back to latest overall if 3.13
        # isn't installed.
        PYENV_VER="$(ls -1 "$HOME/.pyenv/versions" 2>/dev/null | grep -E '^3\.13\.' | sort -V | tail -1)"
        if [ -z "$PYENV_VER" ]; then
            PYENV_VER="$(ls -1 "$HOME/.pyenv/versions" 2>/dev/null | grep -E '^3\.(12|11)\.' | sort -V | tail -1)"
        fi
        if [ -z "$PYENV_VER" ]; then
            PYENV_VER="$(ls -1 "$HOME/.pyenv/versions" 2>/dev/null | sort -V | tail -1)"
        fi
        PYTHON_BIN="$HOME/.pyenv/versions/$PYENV_VER/bin/python3"
        [ -x "$PYTHON_BIN" ] || PYTHON_BIN=""
    fi
    if [ -z "$PYTHON_BIN" ]; then
        for candidate in \
            /opt/homebrew/bin/python3.13 /opt/homebrew/bin/python3.12 \
            /opt/homebrew/bin/python3.11 \
            /usr/local/bin/python3.13 /usr/local/bin/python3.12 \
            /usr/local/bin/python3.11 \
            /opt/homebrew/bin/python3.14 /usr/local/bin/python3.14; do
            if [ -x "$candidate" ]; then
                PYTHON_BIN="$candidate"
                break
            fi
        done
    fi
    if [ -z "$PYTHON_BIN" ]; then
        PYTHON_BIN="$(command -v python3 || true)"
    fi
    return 0
}

python_too_new() {
    # Returns 0 (true) if PYTHON_BIN is 3.14 or newer. Used to gate the
    # "install 3.13" warning so people who explicitly opted into 3.14
    # via $PYTHON aren't blocked.
    [ -n "$PYTHON_BIN" ] && [ -x "$PYTHON_BIN" ] \
        && "$PYTHON_BIN" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 14) else 1)' 2>/dev/null
}

python_is_ok() {
    [ -n "$PYTHON_BIN" ] && [ -x "$PYTHON_BIN" ] \
        && "$PYTHON_BIN" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null
}

detect_python
if ! python_is_ok; then
    PY_VERSION="$("$PYTHON_BIN" -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")' 2>/dev/null || echo "unknown")"
    echo "  Python $PY_VERSION at $PYTHON_BIN is too old (need >= 3.11)." >&2
    ensure_brew
    BREW_BIN="$(find_brew)"
    echo "  Installing python@3.12 via Homebrew (~1-2 min)..." >&2
    if ! "$BREW_BIN" install python@3.12 >/tmp/klava-brew-python.log 2>&1; then
        echo "ERROR: brew install python@3.12 failed — see /tmp/klava-brew-python.log" >&2
        tail -n 20 /tmp/klava-brew-python.log >&2 || true
        exit 1
    fi
    detect_python
    if ! python_is_ok; then
        echo "ERROR: Python still too old after brew install python@3.12." >&2
        echo "       Detected: $PYTHON_BIN (version $("$PYTHON_BIN" -c 'import sys; print(sys.version_info[:2])' 2>/dev/null))" >&2
        exit 1
    fi
    echo "  ✓ Installed Python $("$PYTHON_BIN" -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")')" >&2
fi

# 3.14 wheel-coverage gate. As of late 2026 cryptography / pynacl /
# tiktoken don't ship 3.14 wheels for darwin-arm64 yet, so pip falls back
# to source builds that need a working Rust + cc toolchain. On a fresh
# Mac that's not present and the install fails halfway through, leaving
# the daemons unable to import their deps.
#
# If the only Python we found is 3.14+, try to install python@3.13 via
# brew and switch to it. Honor an explicit $PYTHON override to let power
# users opt back into 3.14 when they know what they're doing.
if [ -z "${PYTHON:-}" ] && python_too_new; then
    PY_TOO_NEW_VERSION="$("$PYTHON_BIN" -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")')"
    echo "" >&2
    echo "  ⚠ Detected Python $PY_TOO_NEW_VERSION at $PYTHON_BIN." >&2
    echo "    Several gateway dependencies (cryptography, pynacl, tiktoken)" >&2
    echo "    don't have 3.14 wheels yet, which forces a source build that" >&2
    echo "    needs Rust + cc and usually fails on a fresh Mac." >&2
    echo "    Trying python@3.13 via Homebrew instead..." >&2
    ensure_brew
    BREW_BIN="$(find_brew)"
    if "$BREW_BIN" install python@3.13 >/tmp/klava-brew-python313.log 2>&1; then
        for candidate in /opt/homebrew/bin/python3.13 /usr/local/bin/python3.13; do
            if [ -x "$candidate" ]; then
                PYTHON_BIN="$candidate"
                break
            fi
        done
        if python_too_new; then
            echo "    ⚠ brew install python@3.13 reported success but PYTHON_BIN is still 3.14+." >&2
            echo "      Continuing on $PYTHON_BIN — gateway deps may need source builds." >&2
        else
            echo "  ✓ Switched to Python $("$PYTHON_BIN" -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")') at $PYTHON_BIN" >&2
        fi
    else
        echo "    ⚠ brew install python@3.13 failed — see /tmp/klava-brew-python313.log" >&2
        echo "      Continuing on Python $PY_TOO_NEW_VERSION. If gateway requirements" >&2
        echo "      install fails later, install Rust (brew install rust) and re-run," >&2
        echo "      or set PYTHON=/path/to/python3.13 ./setup.sh explicitly." >&2
    fi
fi

PYTHON_DIR="$(dirname "$PYTHON_BIN")"
PY_VERSION="$("$PYTHON_BIN" -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")')"

# PEP 660 editable installs require pip >= 21.3. Upgrade in place if older.
PIP_VERSION="$("$PYTHON_BIN" -m pip --version 2>/dev/null | awk '{print $2}' || echo "")"
PIP_MAJMIN="$(printf '%s' "$PIP_VERSION" | awk -F. '{print $1*100 + $2}')"
if [ -n "$PIP_MAJMIN" ] && [ "$PIP_MAJMIN" -lt 2103 ]; then
    echo "  Upgrading pip (have $PIP_VERSION, need >= 21.3 for PEP 660)..."
    "$PYTHON_BIN" -m pip install --quiet --upgrade pip 2>/tmp/klava-pip-upgrade.log || {
        echo "ERROR: pip upgrade failed — see /tmp/klava-pip-upgrade.log" >&2
        tail -n 20 /tmp/klava-pip-upgrade.log >&2 || true
        exit 1
    }
fi

# Resolve __OBSIDIAN_VAULT__ from gateway/config.yaml if present. Fallback to
# the sensible default. We deliberately grep instead of pulling in pyyaml so
# setup.sh stays zero-dep.
CONFIG_YAML="$REPO_DIR/gateway/config.yaml"
if [ -f "$CONFIG_YAML" ]; then
    OBSIDIAN_VAULT_RAW="$(grep -E '^[[:space:]]*obsidian_vault:' "$CONFIG_YAML" | head -1 | sed -E 's/^[[:space:]]*obsidian_vault:[[:space:]]*//; s/[[:space:]]*(#.*)?$//; s/^"//; s/"$//; s/^'\''//; s/'\''$//')"
else
    OBSIDIAN_VAULT_RAW=""
fi
if [ -z "$OBSIDIAN_VAULT_RAW" ]; then
    OBSIDIAN_VAULT_RAW="~/Documents/MyBrain"
fi
# Expand leading ~ to $HOME so downstream consumers can use the path literally.
OBSIDIAN_VAULT="${OBSIDIAN_VAULT_RAW/#\~/$HOME}"

# Ensure the vault directory exists. The cron-scheduler passes it to Claude
# subagents via --add-dir, which fails when the path is missing. New users
# without an Obsidian vault still need a placeholder so heartbeat/reflection
# don't crash on launch.
mkdir -p "$OBSIDIAN_VAULT" 2>/dev/null || true

echo "=== Claude Agent System Setup ==="
echo "  Home:           $HOME"
echo "  Repo:           $REPO_DIR"
echo "  Python:         $PYTHON_BIN (v$PY_VERSION)"
echo "  Obsidian vault: $OBSIDIAN_VAULT"
echo ""

subst() {
    # Substitute all templating placeholders in stdin -> stdout.
    sed -e "s|__HOME__|${HOME}|g" \
        -e "s|__REPO_DIR__|${REPO_DIR}|g" \
        -e "s|__PYTHON_BIN__|${PYTHON_BIN}|g" \
        -e "s|__PYTHON_DIR__|${PYTHON_DIR}|g" \
        -e "s|__OBSIDIAN_VAULT__|${OBSIDIAN_VAULT}|g"
}

# 1. Generate settings.json from template (personal .tpl wins, else .example)
echo "[1/8] Generating settings.json..."
if [ -f "$CLAUDE_DIR/settings.json" ]; then
    echo "  .claude/settings.json exists, skipping"
elif [ -f "$CLAUDE_DIR/settings.json.tpl" ]; then
    subst < "$CLAUDE_DIR/settings.json.tpl" > "$CLAUDE_DIR/settings.json"
    echo "  ✓ Generated .claude/settings.json (from .tpl)"
elif [ -f "$CLAUDE_DIR/settings.json.example" ]; then
    subst < "$CLAUDE_DIR/settings.json.example" > "$CLAUDE_DIR/settings.json"
    echo "  ✓ Generated .claude/settings.json (from .example)"
else
    echo "  ⚠ No settings.json template found"
fi

# 2. Generate and install LaunchAgent plists
echo "[2/8] Installing LaunchAgents..."
INSTALL_DIR="$HOME/Library/LaunchAgents"
mkdir -p "$INSTALL_DIR"

# Read identity.launchd_prefix from gateway/config.yaml so plist Labels
# match. Templates ship as com.vadims.* (brand default). Rewritten here
# if the user configured a different prefix.
LAUNCHD_PREFIX="com.vadims"
if [ -f "$REPO_DIR/gateway/config.yaml" ]; then
    detected="$(awk '/^[[:space:]]*launchd_prefix:/ {print $2; exit}' "$REPO_DIR/gateway/config.yaml" | tr -d '"' | tr -d "'")"
    [ -n "$detected" ] && LAUNCHD_PREFIX="$detected"
fi
echo "  launchd prefix: $LAUNCHD_PREFIX"

for f in "$REPO_DIR/launchagents/"*.plist; do
    [ -f "$f" ] || continue
    src_name="$(basename "$f")"
    # Rename com.local.foo.plist -> <prefix>.foo.plist
    name="${src_name/com.vadims./${LAUNCHD_PREFIX}.}"

    # Skip plists whose target script doesn't exist in this tree
    # (e.g. telegram-daemon lives in a private skills overlay).
    target_script="$(sed -n 's|.*<string>\(__REPO_DIR__/[^<]*\.py\)</string>.*|\1|p' "$f" | head -1 | sed "s|__REPO_DIR__|${REPO_DIR}|g")"
    if [ -n "$target_script" ] && [ ! -f "$target_script" ]; then
        echo "  ⊘ Skipped: $name (target script missing: ${target_script#$REPO_DIR/})"
        continue
    fi

    # Substitute placeholders, then rewrite the Label's com.vadims prefix
    # (template default) to whatever the user configured. Everything else
    # (program args, paths) is unchanged.
    subst < "$f" | sed "s|>com\.vadims\.|>${LAUNCHD_PREFIX}.|g" > "$INSTALL_DIR/$name"
    echo "  ✓ Installed: $name"
done

# 3. Generate cron/jobs.json from example
echo "[3/8] Generating cron/jobs.json..."
if [ ! -f "$REPO_DIR/cron/jobs.json" ]; then
    if [ -f "$REPO_DIR/cron/jobs.json.example" ]; then
        # Defensive: dangling symlinks (e.g. left over from a dev layout
        # where this path is linked into a private config dir) return false
        # for -f but break a subsequent `>` redirect. Unlink to be safe.
        rm -f "$REPO_DIR/cron/jobs.json"
        subst < "$REPO_DIR/cron/jobs.json.example" > "$REPO_DIR/cron/jobs.json"
        echo "  ✓ Generated cron/jobs.json"
    else
        echo "  ⚠ No cron/jobs.json.example found"
    fi
else
    echo "  cron/jobs.json exists, skipping"
fi

# 3b. Migration: heal cron/jobs.json generated from a pre-fix template that
# tried to `git add memory/`. memory/ is gitignored by design, so the chain
# `git add memory/ && git diff ...` always failed and blocked the commit.
# Existing installs never re-run step 3 (file present, "skipping"), so the
# template fix alone doesn't reach them. Patch in-place if we see the
# broken pattern. Idempotent — second run is a no-op.
if [ -f "$REPO_DIR/cron/jobs.json" ]; then
    "$PYTHON_BIN" - "$REPO_DIR/cron/jobs.json" <<'PY'
import json, sys, os
path = sys.argv[1]
with open(path) as f:
    data = json.load(f)
fixed = 0
disabled = 0
for job in data.get("jobs", []):
    cmd = job.get("execution", {}).get("command", "")

    # Heal pre-fix templates that tried `git add memory/`. memory/ is
    # gitignored by design, so the chain `git add memory/ && git diff ...`
    # always failed and blocked the commit. Existing installs never re-run
    # step 3 (file present, "skipping"), so the template fix alone doesn't
    # reach them. Idempotent — second run is a no-op.
    if job.get("id") == "heartbeat-commit" and "git add memory/" in cmd:
        job["execution"]["command"] = cmd.replace(
            "git add memory/ && git diff",
            "git add cron/heartbeat_state.json 2>/dev/null; git diff",
        )
        fixed += 1
    if job.get("id") == "reflection-commit" and "memory/" in cmd:
        job["execution"]["command"] = cmd.replace(
            "git add .claude/CLAUDE.md .claude/skills/ memory/ && git diff",
            "git add .claude/CLAUDE.md .claude/skills/ 2>/dev/null; git diff",
        )
        fixed += 1

    # Disable observability if its target script doesn't ship with the repo.
    # The healthcheck skill is a personal/external skill; on a fresh clone the
    # script doesn't exist and the cron run errors out every hour.
    if job.get("id") == "observability" and job.get("enabled", True):
        # Extract the path argument from the command and check existence.
        # Command shape: "<python> <repo>/.claude/skills/healthcheck/scripts/observability.py"
        target = None
        for tok in cmd.split():
            if tok.endswith("observability.py"):
                target = tok
                break
        if target and not os.path.exists(target):
            job["enabled"] = False
            job.setdefault("_disabled_reason", "healthcheck skill not present in this clone")
            disabled += 1
if fixed or disabled:
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    parts = []
    if fixed:
        parts.append(f"healed {fixed} commit-job command(s)")
    if disabled:
        parts.append(f"disabled {disabled} job(s) whose script is absent")
    print(f"  ✓ Migrated cron/jobs.json: {', '.join(parts)}")
PY
fi

# 4. Create .env from example
echo "[4/8] Checking .env..."
if [ ! -f "$REPO_DIR/.env" ]; then
    if [ -f "$REPO_DIR/.env.example" ]; then
        rm -f "$REPO_DIR/.env"
        cp "$REPO_DIR/.env.example" "$REPO_DIR/.env"
        # Seed a random WEBHOOK_TOKEN if we can
        if command -v python3 >/dev/null 2>&1; then
            TOKEN=$(python3 -c "import secrets; print(secrets.token_hex(32))")
            sed -i.bak "s|^WEBHOOK_TOKEN=$|WEBHOOK_TOKEN=$TOKEN|" "$REPO_DIR/.env" && rm -f "$REPO_DIR/.env.bak"
        fi
        echo "  Created .env — fill in your credentials!"
    else
        echo "  WARNING: No .env.example found"
    fi
else
    echo "  .env exists, skipping"
fi

# 5. Create gateway/config.yaml from example
echo "[5/8] Checking gateway/config.yaml..."
if [ ! -f "$REPO_DIR/gateway/config.yaml" ]; then
    if [ -f "$REPO_DIR/gateway/config.yaml.example" ]; then
        rm -f "$REPO_DIR/gateway/config.yaml"
        cp "$REPO_DIR/gateway/config.yaml.example" "$REPO_DIR/gateway/config.yaml"
        echo "  Created gateway/config.yaml — edit identity + integrations"
    else
        echo "  WARNING: No gateway/config.yaml.example found"
    fi
else
    echo "  gateway/config.yaml exists, skipping"
fi

# 6. Create runtime directories
echo "[6/8] Creating directories..."
mkdir -p "$REPO_DIR/gateway/sessions"
mkdir -p "$REPO_DIR/feed"
mkdir -p "$REPO_DIR/memory"
mkdir -p "$REPO_DIR/vadimgest/data/sources"
mkdir -p "$REPO_DIR/vadimgest/data/checkpoints"
echo "  Done"

# 7. Install Python dependencies + vadimgest editable
echo "[7/8] Installing Python dependencies..."

# Detect PEP 668 lock once (Homebrew / Debian system Python block global pip).
NEEDS_BREAK_SYSTEM=0
if "$PYTHON_BIN" -c 'import sysconfig,os; p=sysconfig.get_path("stdlib"); exit(0 if os.path.exists(os.path.join(p,"EXTERNALLY-MANAGED")) else 1)' 2>/dev/null; then
    NEEDS_BREAK_SYSTEM=1
fi

# 7a. Gateway requirements.txt — PyYAML, flask, apscheduler, etc.
# Without this, tasks.queue and every gateway daemon fail cryptically on fresh
# clones (see GH #3).
if [ -f "$REPO_DIR/requirements.txt" ]; then
    REQ_ARGS=(install -r "$REPO_DIR/requirements.txt" --quiet)
    [ "$NEEDS_BREAK_SYSTEM" = "1" ] && REQ_ARGS+=(--break-system-packages)
    if "$PYTHON_BIN" -m pip "${REQ_ARGS[@]}" 2>/tmp/klava-requirements-install.log; then
        echo "  ✓ gateway requirements installed"
    else
        echo "  ⚠ gateway requirements install failed — see /tmp/klava-requirements-install.log"
    fi
else
    echo "  ⊘ No requirements.txt found, skipping"
fi

if [ -f "$REPO_DIR/vadimgest/pyproject.toml" ]; then
    PIP_ARGS=(install -e "$REPO_DIR/vadimgest[all]" --quiet)
    [ "$NEEDS_BREAK_SYSTEM" = "1" ] && PIP_ARGS+=(--break-system-packages)
    if "$PYTHON_BIN" -m pip "${PIP_ARGS[@]}" 2>/tmp/vadimgest-install.log; then
        echo "  ✓ vadimgest installed (editable, with [all] extras)"
    else
        echo "ERROR: vadimgest install failed — see /tmp/vadimgest-install.log" >&2
        tail -n 20 /tmp/vadimgest-install.log >&2 || true
        exit 1
    fi

    # Smoke test: the launchd plist calls `python -m vadimgest serve`, so the
    # module must be importable from $PYTHON_BIN. If it isn't, the daemon will
    # crash-loop invisibly — fail setup now instead.
    if ! "$PYTHON_BIN" -c "import vadimgest" 2>/dev/null; then
        echo "ERROR: \"$PYTHON_BIN -c 'import vadimgest'\" failed after pip install." >&2
        echo "       The launchd agent will crash-loop. Likely a venv/path mismatch." >&2
        exit 1
    fi

    # Seed ~/.vadimgest/ (home dotfolder, OpenClaw-style: personal data outside the repo)
    VADIMGEST_HOME="$HOME/.vadimgest"
    mkdir -p "$VADIMGEST_HOME"
    if [ ! -e "$VADIMGEST_HOME/config.yaml" ] && [ -f "$REPO_DIR/vadimgest/vadimgest/config.example.yaml" ]; then
        cp "$REPO_DIR/vadimgest/vadimgest/config.example.yaml" "$VADIMGEST_HOME/config.yaml"
        echo "  ✓ Seeded $VADIMGEST_HOME/config.yaml from config.example.yaml"
    fi
    if [ ! -e "$VADIMGEST_HOME/.env" ] && [ -f "$REPO_DIR/vadimgest/.env.example" ]; then
        cp "$REPO_DIR/vadimgest/.env.example" "$VADIMGEST_HOME/.env"
        echo "  ✓ Seeded $VADIMGEST_HOME/.env from .env.example"
    fi

    # Symlink XDG config → ~/.vadimgest/config.yaml so the web UI and any XDG-aware
    # caller see the canonical config instead of auto-generating empty defaults.
    XDG_CONFIG_HOME_DEFAULT="$HOME/.config"
    XDG_DIR="${XDG_CONFIG_HOME:-$XDG_CONFIG_HOME_DEFAULT}/vadimgest"
    mkdir -p "$XDG_DIR"
    if [ ! -e "$XDG_DIR/config.yaml" ]; then
        ln -s "$VADIMGEST_HOME/config.yaml" "$XDG_DIR/config.yaml"
        echo "  ✓ Symlinked $XDG_DIR/config.yaml → ~/.vadimgest/config.yaml"
    elif [ -L "$XDG_DIR/config.yaml" ]; then
        # Repair stale symlinks from earlier layouts (vadimgest/config.yaml or vadimgest/personal/config.yaml)
        current_target="$(readlink "$XDG_DIR/config.yaml")"
        case "$current_target" in
            "$REPO_DIR/vadimgest/config.yaml"|"$REPO_DIR/vadimgest/personal/config.yaml")
                ln -sf "$VADIMGEST_HOME/config.yaml" "$XDG_DIR/config.yaml"
                echo "  ✓ Retargeted $XDG_DIR/config.yaml → ~/.vadimgest/config.yaml"
                ;;
            *)
                echo "  XDG config.yaml symlink exists, skipping"
                ;;
        esac
    else
        echo "  ⚠ $XDG_DIR/config.yaml is a real file — not overwriting"
    fi
else
    echo "ERROR: vadimgest/pyproject.toml missing after submodule init." >&2
    echo "       Check .gitmodules and your git config, then re-run ./setup.sh." >&2
    exit 1
fi

# 8. Check prerequisites
echo "[8/8] Checking prerequisites..."
# Locate `node` (brew installs into /opt/homebrew/bin; may not be on PATH
# in non-login shells). Resolve then add to PATH so downstream npm calls work.
find_node() {
    if command -v node >/dev/null 2>&1; then command -v node; return 0; fi
    for p in /opt/homebrew/bin/node /usr/local/bin/node; do
        [ -x "$p" ] && { echo "$p"; return 0; }
    done
    return 1
}

if ! NODE_BIN="$(find_node)"; then
    echo "  node: MISSING"
    ensure_brew
    BREW_BIN="$(find_brew)"
    echo "  Installing node via Homebrew (~1-2 min)..."
    if "$BREW_BIN" install node >/tmp/klava-brew-node.log 2>&1; then
        NODE_BIN="$(find_node || true)"
        [ -n "$NODE_BIN" ] && echo "  ✓ Installed node: $NODE_BIN"
    else
        echo "  ⚠ brew install node failed — see /tmp/klava-brew-node.log"
    fi
else
    echo "  node: $NODE_BIN"
fi

# Add node's directory to PATH so npm, claude (installed globally by npm), etc.
# resolve for the rest of this script.
if [ -n "${NODE_BIN:-}" ]; then
    NODE_DIR="$(dirname "$NODE_BIN")"
    case ":$PATH:" in *":$NODE_DIR:"*) ;; *) PATH="$NODE_DIR:$PATH" ;; esac
fi

# The official Anthropic installer (`curl -fsSL https://claude.ai/install.sh |
# bash`) drops `claude` into ~/.local/bin. That dir is NOT on the default macOS
# PATH until the user restarts their shell, so setup.sh running in an old
# terminal session wouldn't see it and would needlessly install a second copy
# via npm. Prepend it explicitly.
LOCAL_BIN="$HOME/.local/bin"
case ":$PATH:" in *":$LOCAL_BIN:"*) ;; *) PATH="$LOCAL_BIN:$PATH" ;; esac

# Claude Code CLI: detect existing install from either distribution (the
# official native installer at ~/.local/bin/claude, or npm-global). Only fall
# back to installing if nothing is present. Prefer the official native
# installer — it's self-contained and doesn't drag in node as a runtime dep.
if ! command -v claude >/dev/null 2>&1; then
    echo "  claude: MISSING"
    echo "  Installing via official installer (https://claude.ai/install.sh)..."
    if curl -fsSL https://claude.ai/install.sh | bash >/tmp/klava-claude-install.log 2>&1; then
        # Installer drops into ~/.local/bin, which we already added to PATH.
        if command -v claude >/dev/null 2>&1; then
            echo "  ✓ Installed claude: $(command -v claude)"
        else
            echo "  ⚠ Installer ran but 'claude' still not on PATH — see /tmp/klava-claude-install.log"
        fi
    elif command -v npm >/dev/null 2>&1; then
        echo "  ⚠ Official installer failed — falling back to npm"
        echo "  Installing @anthropic-ai/claude-code via npm (~30s)..."
        if npm install -g @anthropic-ai/claude-code >/tmp/klava-npm-claude.log 2>&1; then
            echo "  ✓ Installed claude: $(command -v claude 2>/dev/null || echo 'in npm global prefix — check PATH')"
        else
            echo "  ⚠ npm install -g @anthropic-ai/claude-code failed — see /tmp/klava-npm-claude.log"
        fi
    else
        echo "  ⚠ Neither official installer nor npm worked — install claude manually:"
        echo "    curl -fsSL https://claude.ai/install.sh | bash"
    fi
else
    echo "  claude: $(command -v claude)"
fi

echo "  python3: $PYTHON_BIN"

# Optional CLI auth tools for the wizard: gh (GitHub) + gogcli (Google).
# Best-effort install — wizard falls back to manual install instructions if
# these fail.
if BREW_BIN="$(find_brew)" 2>/dev/null; then
    if ! command -v gh >/dev/null 2>&1; then
        echo "  Installing gh (GitHub CLI)..."
        "$BREW_BIN" install gh >/tmp/klava-brew-gh.log 2>&1 && \
            echo "  ✓ gh installed" || \
            echo "  ⚠ gh install failed — see /tmp/klava-brew-gh.log"
    fi
    if ! command -v gog >/dev/null 2>&1; then
        echo "  Installing gogcli (Google CLI)..."
        "$BREW_BIN" install gogcli >/tmp/klava-brew-gogcli.log 2>&1 && \
            echo "  ✓ gogcli installed" || \
            echo "  ⚠ gogcli install failed — see /tmp/klava-brew-gogcli.log"
    fi
    # gog defaults to macOS Keychain which requires a logged-in GUI session
    # to be unlocked. File-based keyring works in launchd subprocesses too.
    if command -v gog >/dev/null 2>&1; then
        if [ "$(gog config get keyring_backend 2>/dev/null)" != "file" ]; then
            gog config set keyring_backend file >/dev/null 2>&1 && \
                echo "  ✓ gog keyring_backend=file (avoids locked-keychain failures)"
        fi
        # Seed the shared Klava OAuth Desktop client if the user doesn't
        # have credentials.json yet. Users who want their own OAuth client
        # (to isolate API quota) can overwrite it later. See klava-shared/
        # README for the trade-offs.
        GOG_CRED_DIR="$HOME/Library/Application Support/gogcli"
        GOG_CRED="$GOG_CRED_DIR/credentials.json"
        SHARED_CRED="$REPO_DIR/klava-shared/gog-credentials.json"
        if [ ! -f "$GOG_CRED" ] && [ -f "$SHARED_CRED" ]; then
            mkdir -p "$GOG_CRED_DIR"
            cp "$SHARED_CRED" "$GOG_CRED"
            echo "  ✓ Seeded shared gog OAuth credentials (override with your own in $GOG_CRED)"
        fi
        # gog's file-keyring encrypts stored OAuth refresh tokens and
        # interactively prompts for a passphrase — which hangs any
        # non-TTY subprocess (wizard, cron-spawned sync daemons). Pin a
        # fixed passphrase via launchctl so all launchd agents inherit
        # it, unblocks `gog auth add` end-to-end. Local-at-rest only;
        # the keyring file is already protected by home-dir permissions.
        launchctl setenv GOG_KEYRING_PASSWORD "klava-default-keyring" 2>/dev/null && \
            echo "  ✓ Set launchd GOG_KEYRING_PASSWORD (inherited by daemons)"
    fi
fi

# Backfill __CLAUDE_CLI__ and __NODE_DIR__ placeholders in gateway/config.yaml
# now that we know where the binaries actually landed. (subst at step [5/8]
# leaves these untouched because it doesn't yet know the install paths.)
if [ -f "$REPO_DIR/gateway/config.yaml" ]; then
    CLAUDE_CLI_PATH="$(command -v claude 2>/dev/null || true)"
    NODE_DIR_PATH=""
    [ -n "${NODE_BIN:-}" ] && NODE_DIR_PATH="$(dirname "$NODE_BIN")"
    if [ -n "$CLAUDE_CLI_PATH" ]; then
        sed -i.bak "s|__CLAUDE_CLI__|$CLAUDE_CLI_PATH|g" "$REPO_DIR/gateway/config.yaml"
    fi
    if [ -n "$NODE_DIR_PATH" ]; then
        sed -i.bak "s|__NODE_DIR__|$NODE_DIR_PATH|g" "$REPO_DIR/gateway/config.yaml"
    fi
    rm -f "$REPO_DIR/gateway/config.yaml.bak"
    # Any placeholders still present => tool wasn't installed; fall back to a
    # sensible default so the config is at least parseable.
    sed -i.bak "s|__CLAUDE_CLI__|claude|g; s|__NODE_DIR__|/opt/homebrew/bin|g" \
        "$REPO_DIR/gateway/config.yaml"
    rm -f "$REPO_DIR/gateway/config.yaml.bak"
fi

# Build the dashboard if missing and node is available
if [ ! -f "$REPO_DIR/tools/dashboard/dist/index.html" ]; then
    if command -v npm >/dev/null 2>&1; then
        echo ""
        echo "  Building dashboard..."
        (cd "$REPO_DIR/tools/dashboard/react-app" && npm install --silent && npm run build --silent) \
            && echo "  ✓ Dashboard built" \
            || echo "  ⚠ Dashboard build failed — run manually in tools/dashboard/react-app"
    else
        echo ""
        echo "  Dashboard not built — install Node and run:"
        echo "    cd tools/dashboard/react-app && npm install && npm run build"
    fi
fi

# Auto-load launchd agents. Each plist is unloaded first (errors ignored) to
# make this idempotent — loading an already-loaded agent throws "Already
# loaded" noise.
echo ""
echo "Loading launchd agents..."
LOADED=0
FAILED=0
for plist in "$INSTALL_DIR"/${LAUNCHD_PREFIX:-com.vadims}.*.plist; do
    [ -f "$plist" ] || continue
    label="$(basename "$plist" .plist)"
    launchctl unload "$plist" 2>/dev/null || true
    if launchctl load "$plist" 2>/dev/null; then
        echo "  ✓ loaded $label"
        LOADED=$((LOADED + 1))
    else
        echo "  ⚠ failed to load $label"
        FAILED=$((FAILED + 1))
    fi
done

# Wait for the webhook-server to be listening before opening the browser,
# up to 10 seconds. Otherwise the first request to localhost:18788 would
# 404 because Flask hasn't finished booting.
DASHBOARD_URL="http://localhost:18788/dashboard?firstrun=1"
echo ""
echo "Waiting for dashboard to come up on localhost:18788..."
for i in $(seq 1 20); do
    if curl -sf -o /dev/null --max-time 1 http://localhost:18788/dashboard 2>/dev/null; then
        echo "  ✓ dashboard is up"
        break
    fi
    sleep 0.5
done

# Open the dashboard in the user's default browser. The ?firstrun=1 hint
# tells the React app to auto-open the setup wizard modal.
if command -v open >/dev/null 2>&1; then
    open "$DASHBOARD_URL" 2>/dev/null || true
    echo "  ✓ opened $DASHBOARD_URL"
fi

echo ""
echo "=== Setup complete ==="
echo ""
echo "Dashboard: $DASHBOARD_URL"
echo "The setup wizard should auto-open. Follow it to finish connecting Claude,"
echo "Obsidian, Telegram, and vadimgest sources."
echo ""
if [ "${CLAUDE_CONFIG_DIR:-}" != "$CLAUDE_DIR" ]; then
    echo "(Optional) add to ~/.zshrc so the claude CLI sees this project's config:"
    echo "  export CLAUDE_CONFIG_DIR=\"$CLAUDE_DIR\""
    echo ""
fi
