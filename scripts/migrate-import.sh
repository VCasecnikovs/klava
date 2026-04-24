#!/bin/bash
set -euo pipefail

# Migration Import Script - run on NEW machine
# Assumes: migration bundle at ~/migration/ and repo already cloned/rsynced

MIGRATION_DIR="${1:-$HOME/migration}"
REPO="$HOME/Documents/GitHub/claude"

echo "=== Klava Migration Import ==="
echo "Source: $MIGRATION_DIR"
echo ""

# Preflight
if [ ! -d "$MIGRATION_DIR" ]; then
    echo "ERROR: $MIGRATION_DIR not found"
    echo "First transfer the bundle from the old machine"
    exit 1
fi

# 1. SSH KEYS
echo "[1/7] Installing SSH keys..."
if [ -d "$MIGRATION_DIR/ssh-keys" ]; then
    cp -r "$MIGRATION_DIR/ssh-keys" ~/.ssh
    chmod 700 ~/.ssh
    chmod 600 ~/.ssh/id_* 2>/dev/null || true
    chmod 644 ~/.ssh/*.pub 2>/dev/null || true
    echo "  -> SSH keys installed"
else
    echo "  -> SKIP: no SSH keys in bundle"
fi

# 2. SECRETS
echo "[2/7] Installing secrets..."
if [ -f "$MIGRATION_DIR/secrets.sh" ]; then
    # Append to .zshenv (loads for ALL shells including launchd children)
    cat "$MIGRATION_DIR/secrets.sh" >> ~/.zshenv
    source "$MIGRATION_DIR/secrets.sh"
    echo "  -> Secrets added to ~/.zshenv"
fi

# Copy .env files back
for dotenv in "$MIGRATION_DIR"/*-dotenv; do
    [ -f "$dotenv" ] || continue
    dirname=$(basename "$dotenv" | sed 's/-dotenv//')
    if [ "$dirname" = "claude" ]; then
        cp "$dotenv" "$REPO/.env"
    elif [ "$dirname" = "vadimgest" ]; then
        cp "$dotenv" "$REPO/vadimgest/.env"
    fi
done
echo "  -> .env files restored"

# 3. CLICKHOUSE
echo "[3/7] Installing ClickHouse configs..."
if [ -d "$MIGRATION_DIR/clickhouse-client" ]; then
    cp -r "$MIGRATION_DIR/clickhouse-client" ~/.clickhouse-client
    echo "  -> ~/.clickhouse-client installed"
fi

# 4. SHELL CONFIG
echo "[4/7] Setting up shell..."
if [ -f "$MIGRATION_DIR/zshrc-additions.sh" ]; then
    echo "" >> ~/.zshrc
    echo "# === Klava additions (migrated $(date +%Y-%m-%d)) ===" >> ~/.zshrc
    cat "$MIGRATION_DIR/zshrc-additions.sh" >> ~/.zshrc
    echo "  -> Added to ~/.zshrc"
fi

# 5. BREW ESSENTIALS (background - takes time)
echo "[5/7] Installing brew essentials (background)..."
if command -v brew &>/dev/null; then
    if [ -f "$MIGRATION_DIR/brew-essentials.sh" ]; then
        nohup bash "$MIGRATION_DIR/brew-essentials.sh" > /tmp/brew-install.log 2>&1 &
        echo "  -> Running in background (PID: $!, log: /tmp/brew-install.log)"
    fi
else
    echo "  -> SKIP: Homebrew not installed. Run:"
    echo '    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'
    echo "    Then: bash $MIGRATION_DIR/brew-essentials.sh"
fi

# 6. LAUNCHAGENTS
echo "[6/7] Installing LaunchAgents..."
if [ -d "$MIGRATION_DIR/launchagents" ]; then
    mkdir -p ~/Library/LaunchAgents
    # Update paths in plists to new user
    NEW_USER=$(whoami)
    for plist in "$MIGRATION_DIR/launchagents"/*.plist; do
        filename=$(basename "$plist")
        sed "s|/Users/[a-zA-Z0-9_]*|/Users/$NEW_USER|g" "$plist" > ~/Library/LaunchAgents/"$filename"
    done
    echo "  -> Plists copied (paths updated for user: $NEW_USER)"
    echo "  -> Load them with: launchctl load ~/Library/LaunchAgents/*.plist"
    echo "  -> (wait for brew essentials to finish first)"
fi

# 7. CLAUDE CODE AUTH
echo "[7/7] Claude Code auth..."
if command -v claude &>/dev/null; then
    echo "  -> Claude Code found. Run: claude auth"
else
    echo "  -> Claude Code not yet installed. After brew-essentials:"
    echo "     npm install -g @anthropic-ai/claude-code"
    echo "     claude auth"
fi

# Also re-authenticate GitHub
if command -v gh &>/dev/null; then
    gh auth status 2>/dev/null || echo "  -> Run: gh auth login"
fi

echo ""
echo "=== Import complete ==="
echo ""
echo "Remaining manual steps:"
echo "  1. Wait for brew to finish: tail -f /tmp/brew-install.log"
echo "  2. Auth Claude: CLAUDE_CONFIG_DIR=$REPO/.claude claude auth"
echo "  3. Auth GitHub: gh auth login"
echo "  4. Open new terminal (to load .zshrc changes)"
echo "  5. Load daemons: for p in ~/Library/LaunchAgents/com.local.*.plist; do launchctl load \"\$p\"; done"
echo "  6. Check dashboard: http://localhost:18788/dashboard"
echo ""
echo "To verify everything works:"
echo "  claude auth status"
echo "  ch-vox 'SELECT 1'"
echo "  curl -s localhost:18788/api/health | jq ."
