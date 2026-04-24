#!/bin/bash
# Claude Agent - one-click bootstrap for macOS.
#
# Double-click this file in Finder (or `./bootstrap.command` in a terminal).
# It takes a fresh macOS machine from zero to a running dashboard.
#
# Steps:
#   1. Install Homebrew if missing (with consent)
#   2. Install git, python, node via Homebrew if missing
#   3. Initialize git submodules (vadimgest data-lake, optional)
#   4. Install Claude Code CLI (optional)
#   5. Create a Python venv inside the repo and pip install
#   6. Build the dashboard (npm install + npm run build)
#   7. Run setup.sh to render configs and plists
#   8. Export CLAUDE_CONFIG_DIR in the shell profile
#   9. Load the webhook-server launchd job
#  10. Open the dashboard in the browser
#
# After this completes the user does the rest in the browser GUI:
#   - fill in identity, telegram, integrations (Settings tab)
#   - authenticate Claude Code (one terminal command)
#   - enable cron jobs

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$REPO_DIR"

# Colored output helpers — stdout goes to a Terminal window on double-click.
bold()  { printf "\033[1m%s\033[0m\n" "$*"; }
step()  { printf "\n\033[1;34m[%s]\033[0m %s\n" "$1" "$2"; }
ok()    { printf "  \033[32m✓\033[0m %s\n" "$*"; }
warn()  { printf "  \033[33m⚠\033[0m %s\n" "$*"; }
fail()  { printf "  \033[31m✗\033[0m %s\n" "$*" >&2; }

confirm() {
    # $1 = prompt, returns 0 if yes
    printf "  %s [Y/n] " "$1"
    read -r answer
    case "$answer" in
        ""|y|Y|yes|YES) return 0 ;;
        *) return 1 ;;
    esac
}

bold "=== Claude Agent bootstrap ==="
echo "Repo: $REPO_DIR"

# 1. Homebrew
step 1 "Homebrew"
if command -v brew >/dev/null 2>&1; then
    ok "Homebrew installed: $(brew --prefix)"
else
    warn "Homebrew not found."
    if confirm "Install Homebrew now? (opens apple.com install script)"; then
        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
        # Refresh PATH for current shell
        if [ -x /opt/homebrew/bin/brew ]; then
            eval "$(/opt/homebrew/bin/brew shellenv)"
        elif [ -x /usr/local/bin/brew ]; then
            eval "$(/usr/local/bin/brew shellenv)"
        fi
        ok "Homebrew installed"
    else
        fail "Cannot continue without Homebrew. Install manually from https://brew.sh and re-run."
        exit 1
    fi
fi

# 2. System deps
step 2 "System tools (git, python@3.12, node)"
need_install=()
command -v git >/dev/null 2>&1 || need_install+=(git)
command -v python3 >/dev/null 2>&1 || need_install+=(python@3.12)
command -v node >/dev/null 2>&1 || need_install+=(node)

if [ ${#need_install[@]} -gt 0 ]; then
    echo "  Missing: ${need_install[*]}"
    if confirm "Install via Homebrew now?"; then
        brew install "${need_install[@]}"
    else
        fail "Cannot continue without: ${need_install[*]}"
        exit 1
    fi
fi
ok "git     $(git --version | awk '{print $3}')"
ok "python3 $(python3 --version | awk '{print $2}')"
ok "node    $(node --version)"

# 3. Submodules (vadimgest data-lake, optional)
step 3 "Initializing submodules"
if [ -f "$REPO_DIR/.gitmodules" ]; then
    if git submodule update --init --recursive 2>/dev/null; then
        ok "Submodules initialized"
    else
        warn "Submodule init failed (private repo or no access). Vadimgest features will be disabled until you clone it manually into vadimgest/."
    fi
else
    ok "No .gitmodules — skipping"
fi

# 4. Claude Code CLI
step 4 "Claude Code CLI"
if command -v claude >/dev/null 2>&1; then
    ok "claude: $(command -v claude)"
else
    warn "claude CLI not installed"
    if confirm "Install @anthropic-ai/claude-code globally via npm?"; then
        npm install -g @anthropic-ai/claude-code
        ok "Installed"
    else
        warn "Skipping — dashboard will work, but Claude sessions will not until you install it."
    fi
fi

# 5. Python venv + dependencies
step 5 "Python venv + dependencies"
VENV_DIR="$REPO_DIR/.venv"
if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR"
    ok "Created .venv"
fi
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"
pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet
ok "Python deps installed"

# Keep setup.sh + launchd plists pointing at the venv python
export PYTHON="$VENV_DIR/bin/python3"

# 6. Dashboard build
step 6 "Dashboard"
if [ ! -f "$REPO_DIR/tools/dashboard/dist/index.html" ]; then
    (cd "$REPO_DIR/tools/dashboard/react-app" && npm install --silent && npm run build --silent)
    ok "Dashboard built"
else
    ok "Dashboard already built"
fi

# 7. setup.sh (renders settings.json, plists, .env, config.yaml)
step 7 "Rendering configs and LaunchAgents"
./setup.sh

# 8. Shell profile — CLAUDE_CONFIG_DIR
step 8 "Shell profile"
CLAUDE_DIR="$REPO_DIR/.claude"
PROFILE="$HOME/.zshrc"
[ -f "$HOME/.bash_profile" ] && [ ! -f "$HOME/.zshrc" ] && PROFILE="$HOME/.bash_profile"
if grep -q "CLAUDE_CONFIG_DIR=\"$CLAUDE_DIR\"" "$PROFILE" 2>/dev/null; then
    ok "CLAUDE_CONFIG_DIR already in $PROFILE"
else
    {
        echo ""
        echo "# Added by claude bootstrap.command"
        echo "export CLAUDE_CONFIG_DIR=\"$CLAUDE_DIR\""
    } >> "$PROFILE"
    ok "Added CLAUDE_CONFIG_DIR to $PROFILE"
fi
export CLAUDE_CONFIG_DIR="$CLAUDE_DIR"

# 9. Load webhook-server so the dashboard is reachable
# (cron + tg-gateway stay off until user configures them in the Settings tab.)
step 9 "Starting webhook-server"
LA_DIR="$HOME/Library/LaunchAgents"
WEBHOOK_PLIST=""
for f in "$LA_DIR"/*.webhook-server.plist; do
    [ -f "$f" ] && WEBHOOK_PLIST="$f" && break
done
if [ -n "$WEBHOOK_PLIST" ]; then
    launchctl unload "$WEBHOOK_PLIST" 2>/dev/null || true
    launchctl load "$WEBHOOK_PLIST"
    ok "Loaded $(basename "$WEBHOOK_PLIST")"
else
    warn "No webhook-server plist found in $LA_DIR. Run setup.sh again or check launchagents/."
fi

# 10. Wait for the dashboard to come up, then open the browser
step 10 "Opening dashboard"
PORT=18788
for i in 1 2 3 4 5 6 7 8 9 10; do
    if curl -s "http://localhost:$PORT/dashboard" >/dev/null 2>&1; then
        open "http://localhost:$PORT/dashboard#setup"
        ok "Dashboard is up at http://localhost:$PORT/dashboard"
        break
    fi
    sleep 1
    [ "$i" = 10 ] && warn "Dashboard didn't respond yet. Check /tmp/webhook-server.err.log"
done

bold ""
bold "=== Bootstrap complete ==="
echo ""
echo "Finish setup in the browser:"
echo "  1. Open the Settings tab and fill in the required fields:"
echo "       - identity.assistant_name, identity.user_name"
echo "       - you.name, you.email, you.timezone"
echo "       - telegram.bot_token + telegram.chat_id (optional, for mobile)"
echo "  2. Authenticate Claude Code in a terminal:"
echo "       CLAUDE_CONFIG_DIR=\"$CLAUDE_DIR\" claude login"
echo ""
echo "To enable scheduled jobs and the Telegram bot later (substitute the"
echo "prefix you set in identity.launchd_prefix; default is com.vadims):"
echo "  for f in ~/Library/LaunchAgents/com.vadims.*.plist; do launchctl load \"\$f\"; done"
echo ""
