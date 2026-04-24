#!/bin/bash
# Fully isolated setup.sh test inside a throwaway Docker container.
#
# Usage: ./scripts/test-setup-docker.sh
#
# Unlike test-setup.sh (macOS-native, redirects HOME but shares system git
# config + pyenv + network), this spins up a clean Debian container with:
#   - fresh /home/tester
#   - no user git config
#   - isolated Python
#   - no access to your real repo (bind-mounted read-only)
#
# Caveats: Linux, so it won't catch macOS-specific quirks (BSD sed, pyenv
# shim resolution, $HOME/Library paths). Use test-setup.sh for those.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
IMAGE="klava-setup-test:latest"

if ! command -v docker >/dev/null 2>&1; then
    echo "ERROR: docker not found on PATH." >&2
    echo "       Install Docker Desktop or Colima first." >&2
    exit 1
fi

if ! docker info >/dev/null 2>&1; then
    echo "ERROR: docker daemon not running. Start Docker Desktop / Colima." >&2
    exit 1
fi

echo "[1/3] Building test image..."
docker build -q -t "$IMAGE" - <<'DOCKERFILE' >/dev/null
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        git rsync curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -m -u 1000 -s /bin/bash tester
USER tester
WORKDIR /home/tester

# Setup.sh detects Homebrew / pyenv; neither exists here, so it falls through
# to `command -v python3`. That's the fresh-clone code path we want to test.
ENV PATH=/home/tester/.local/bin:/usr/local/bin:/usr/bin:/bin
DOCKERFILE

echo "[2/3] Running setup.sh inside container..."
echo "-------------------------------------------------------------------"

# Read-only bind mount of the repo so the container can't mutate your tree.
# The container copies it into /home/tester/klava before running.
docker run --rm \
    -v "$REPO_DIR":/repo:ro \
    "$IMAGE" \
    bash -euc '
        rsync -a \
            --exclude=node_modules \
            --exclude=.venv \
            --exclude=tools/dashboard/react-app/node_modules \
            --exclude=tools/dashboard/react-app/dist \
            /repo/ ~/klava/

        # Simulate fresh clone: empty the submodule working tree.
        rm -rf ~/klava/vadimgest
        mkdir -p ~/klava/vadimgest

        # macOS-flavored LaunchAgents dir that setup.sh expects to write into.
        mkdir -p ~/Library/LaunchAgents

        cd ~/klava
        ./setup.sh
        STATUS=$?

        echo
        echo "=== Post-setup verification ==="
        echo "-- LaunchAgents rendered:"
        ls ~/Library/LaunchAgents/ 2>/dev/null || echo "(none)"
        echo "-- ~/.vadimgest contents:"
        ls -la ~/.vadimgest/ 2>/dev/null || echo "(missing)"
        echo "-- XDG symlink:"
        ls -la ~/.config/vadimgest/config.yaml 2>/dev/null || echo "(missing)"
        echo "-- vadimgest importable:"
        python3 -c "import vadimgest; print(\"OK:\", vadimgest.__file__)" 2>&1 || true
        echo "-- plist placeholder check (should show NO __PLACEHOLDER__ matches):"
        grep -l "__[A-Z_]*__" ~/Library/LaunchAgents/*.plist 2>/dev/null \
            && echo "FAIL: placeholders not substituted" \
            || echo "OK: all placeholders substituted"

        exit $STATUS
    '

STATUS=$?
echo "-------------------------------------------------------------------"
echo "[3/3] Container exited with status: $STATUS"
echo
if [ $STATUS -eq 0 ]; then
    echo "✓ setup.sh survived a clean-room Linux run."
else
    echo "✗ setup.sh failed in the container. See log above."
fi

exit $STATUS
