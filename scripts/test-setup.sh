#!/bin/bash
# Sandbox-test setup.sh without touching real $HOME or system Python.
#
# Usage: ./scripts/test-setup.sh [--keep]
#
# Copies the repo (including uncommitted edits) into a tempdir, wipes the
# vadimgest/ submodule to simulate a fresh clone, redirects HOME to a scratch
# subdir, creates an isolated Python venv, and runs setup.sh against it.
#
# --keep   leave the sandbox on disk (default: print path, you clean up)

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SCRATCH="$(mktemp -d -t klava-setup-test.XXXXXX)"
SANDBOX_HOME="$SCRATCH/home"
SANDBOX_REPO="$SCRATCH/klava"
VENV="$SCRATCH/venv"

echo "=== Sandbox ==="
echo "  Scratch dir: $SCRATCH"
echo "  Real repo:   $REPO_DIR"
echo "  Fake HOME:   $SANDBOX_HOME"
echo ""

echo "[1/4] Copying repo (with uncommitted edits)..."
# rsync is faster than cp -R for repos with .git/ and node_modules/
rsync -a \
    --exclude='node_modules' \
    --exclude='.venv' \
    --exclude='tools/dashboard/react-app/node_modules' \
    --exclude='tools/dashboard/react-app/dist' \
    "$REPO_DIR/" "$SANDBOX_REPO/"

echo "[2/4] Simulating fresh clone: wiping vadimgest/ submodule tree..."
# Leaves .gitmodules + submodule metadata in .git/modules/, but empties the
# working tree so the auto-init path in setup.sh has something to do.
rm -rf "$SANDBOX_REPO/vadimgest"
mkdir -p "$SANDBOX_REPO/vadimgest"

echo "[3/4] Creating isolated Python venv..."
mkdir -p "$SANDBOX_HOME/Library/LaunchAgents"
mkdir -p "$SANDBOX_HOME/.config"
python3 -m venv "$VENV"
"$VENV/bin/pip" install --quiet --upgrade pip

echo "[4/4] Running setup.sh with HOME=$SANDBOX_HOME, PYTHON=$VENV/bin/python"
echo "-------------------------------------------------------------------"
set +e
cd "$SANDBOX_REPO"
HOME="$SANDBOX_HOME" PYTHON="$VENV/bin/python" ./setup.sh
STATUS=$?
set -e
echo "-------------------------------------------------------------------"

echo ""
echo "=== Exit status: $STATUS ==="
echo ""
echo "=== Files created in sandbox HOME ==="
find "$SANDBOX_HOME" -maxdepth 4 \( -type f -o -type l \) 2>/dev/null \
    | sed "s|$SANDBOX_HOME|~|" | sort | head -50
echo ""
echo "=== Rendered plists (check placeholder substitution) ==="
for f in "$SANDBOX_HOME/Library/LaunchAgents"/*.plist; do
    [ -f "$f" ] || continue
    echo "--- $(basename "$f") ---"
    grep -E '(Program|WorkingDirectory|Label)' "$f" | head -10
done

echo ""
echo "=== vadimgest importable from sandbox venv? ==="
if "$VENV/bin/python" -c "import vadimgest; print('OK:', vadimgest.__file__)" 2>&1; then
    echo "✓ module resolves"
else
    echo "✗ module missing — setup.sh should have caught this"
fi

echo ""
if [ "${1:-}" = "--keep" ]; then
    echo "Sandbox kept at: $SCRATCH"
else
    echo "Sandbox: $SCRATCH"
    echo "Clean up with: rm -rf $SCRATCH"
fi

exit $STATUS
