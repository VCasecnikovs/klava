#!/bin/bash
set -euo pipefail

# Migration Export Script - run on OLD machine
# Creates a minimal bundle for fast transfer to new laptop

BUNDLE_DIR="/tmp/klava-migration"
rm -rf "$BUNDLE_DIR"
mkdir -p "$BUNDLE_DIR"

echo "=== Klava Migration Export ==="
echo "Exporting secrets + configs + data..."
echo ""

# 1. SECRETS FILE (most critical - everything in one place)
echo "[1/6] Extracting secrets..."
cat > "$BUNDLE_DIR/secrets.sh" << 'SECRETS_EOF'
#!/bin/bash
# Source this on the new machine: source ~/secrets.sh
# Then add to ~/.zshenv or ~/.zshrc

SECRETS_EOF

# Pull from current env
for var in TELEGRAM_API_ID TELEGRAM_API_HASH TELEGRAM_SESSION_STRING \
           GITHUB_PERSONAL_ACCESS_TOKEN SIGNAL_USER_ID GRAFANA_ASTRUM_TOKEN \
           GEMINI_API_KEY; do
    val="${!var:-}"
    if [ -n "$val" ]; then
        echo "export ${var}=\"${val}\"" >> "$BUNDLE_DIR/secrets.sh"
    fi
done

# Also grab from .env files
for envfile in ~/Documents/GitHub/claude/.env ~/Documents/GitHub/vadimgest/.env; do
    if [ -f "$envfile" ]; then
        cp "$envfile" "$BUNDLE_DIR/$(basename $(dirname $envfile))-dotenv"
    fi
done
chmod 600 "$BUNDLE_DIR/secrets.sh" "$BUNDLE_DIR"/*-dotenv 2>/dev/null || true
echo "  -> secrets.sh + .env files saved"

# 2. SSH KEYS
echo "[2/6] Copying SSH keys..."
cp -r ~/.ssh "$BUNDLE_DIR/ssh-keys"
chmod 700 "$BUNDLE_DIR/ssh-keys"
echo "  -> ~/.ssh copied"

# 3. CLICKHOUSE CONFIGS
echo "[3/6] Copying ClickHouse configs..."
cp -r ~/.clickhouse-client "$BUNDLE_DIR/clickhouse-client" 2>/dev/null || echo "  -> no ClickHouse configs"
echo "  -> ~/.clickhouse-client copied"

# 4. SHELL CONFIG (just the relevant parts)
echo "[4/6] Extracting shell config..."
cat > "$BUNDLE_DIR/zshrc-additions.sh" << 'ZSHRC_EOF'
# === Klava / Claude Code setup ===
# Add these to ~/.zshrc on new machine

# Claude Code
export CLAUDE_CONFIG_DIR="/Users/$(whoami)/Documents/GitHub/claude/.claude"
export PATH="$HOME/bin:$PATH"
export PATH="$HOME/.local/bin:$PATH"

# Aliases
alias ch-vox='clickhouse-client -C ~/.clickhouse-client/vox.xml'
alias ch-astrum='clickhouse-client -C ~/.clickhouse-client/astrum.xml'
alias clauded="claude --allow-dangerously-skip-permissions --permission-mode bypassPermissions"
alias qmd='cd ~/Documents/GitHub/claude/qmd && bun run qmd'

# Bun
export BUN_INSTALL="$HOME/.bun"
export PATH="$BUN_INSTALL/bin:$PATH"

# NVM
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"

# Pyenv
export PYENV_ROOT="$HOME/.pyenv"
export PATH="$PYENV_ROOT/bin:$PATH"
eval "$(pyenv init -)"
ZSHRC_EOF
echo "  -> zshrc-additions.sh created"

# 5. BREWFILE
echo "[5/6] Generating Brewfile..."
brew bundle dump --file="$BUNDLE_DIR/Brewfile" --force 2>/dev/null || echo "  -> brew bundle dump failed, skipping"

# Also create a minimal essentials file
cat > "$BUNDLE_DIR/brew-essentials.sh" << 'BREW_EOF'
#!/bin/bash
# Essential packages only - install these first, rest can wait
brew install python pyenv pyenv-virtualenv
brew install node yarn
brew install git gh git-lfs
brew install clickhouse
brew install signal-cli
brew install tmux ripgrep jq sqlite
brew install ffmpeg
brew install uv

# Bun (not via brew)
curl -fsSL https://bun.sh/install | bash

# Claude Code
npm install -g @anthropic-ai/claude-code
BREW_EOF
chmod +x "$BUNDLE_DIR/brew-essentials.sh"
echo "  -> Brewfile + brew-essentials.sh created"

# 6. LAUNCHAGENTS
echo "[6/6] Copying LaunchAgent plists..."
mkdir -p "$BUNDLE_DIR/launchagents"
cp ~/Library/LaunchAgents/com.local.*.plist "$BUNDLE_DIR/launchagents/" 2>/dev/null || true
echo "  -> LaunchAgent plists copied"

# Summary
echo ""
echo "=== Export complete ==="
du -sh "$BUNDLE_DIR"
echo ""
echo "Bundle location: $BUNDLE_DIR"
echo ""
echo "=== TRANSFER PLAN ==="
echo ""
echo "Option A: Both machines on same WiFi (fastest)"
echo "  NEW machine: mkdir -p ~/migration && cd ~/migration"
echo "  OLD machine: rsync -avz --progress $BUNDLE_DIR/ NEW_IP:~/migration/"
echo "  OLD machine: rsync -avz --progress ~/Documents/GitHub/claude/ NEW_IP:~/Documents/GitHub/claude/ \\"
echo "               --exclude='.claude/projects' --exclude='.claude/shell-snapshots' \\"
echo "               --exclude='.claude/telemetry' --exclude='.claude/debug' \\"
echo "               --exclude='.claude/logs' --exclude='.git' \\"
echo "               --exclude='node_modules' --exclude='__pycache__' \\"
echo "               --exclude='.venv'"
echo "  OLD machine: rsync -avz --progress ~/Documents/MyBrain/ NEW_IP:~/Documents/MyBrain/"
echo "  OLD machine: rsync -avz --progress ~/.vadimsearch/ NEW_IP:~/.vadimsearch/"
echo ""
echo "Option B: AirDrop / USB drive"
echo "  tar -cf /tmp/klava-bundle.tar -C /tmp klava-migration"
echo "  Estimated: ~5MB (secrets+configs only)"
echo ""
echo "  For data (do in background):"
echo "  tar -cf /tmp/klava-data.tar \\"
echo "    -C ~ Documents/MyBrain \\"
echo "    -C ~ .vadimsearch \\"
echo "    --exclude='*.pyc' --exclude='__pycache__'"
echo "  Estimated: ~3GB"
echo ""
echo "Then run migrate-import.sh on the new machine."
