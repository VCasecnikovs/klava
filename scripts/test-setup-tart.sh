#!/bin/bash
# End-to-end new-user UX test in an ephemeral macOS VM via Tart.
#
# Boots a real macOS VM with GUI, rsyncs this repo in, runs setup.sh, loads
# launchd agents. You get a window showing a "fresh Mac" where you can open
# Safari, hit the dashboard, click through the wizard, and find UX bugs.
#
# Usage:
#   ./scripts/test-setup-tart.sh           # reset + rsync local repo + run setup.sh (default)
#   ./scripts/test-setup-tart.sh --clone   # reset + git clone from GitHub; leaves setup.sh for you
#   ./scripts/test-setup-tart.sh --keep    # reuse existing VM, re-sync repo only
#   ./scripts/test-setup-tart.sh --destroy # nuke the VM and exit
#
# Why --clone: rsync hides bugs in the "fresh git clone" path — submodule auth,
# dist/ artifacts, .gitignore coverage, etc. --clone boots a VM that only has
# what a real new user would get (`git clone` of the public repo). The private
# vadimgest submodule will fail to init until you run `gh auth login` inside
# the VM. That failure path itself is part of what we want to test.
#
# Requirements:
#   brew install cirruslabs/cli/tart hudochenkov/sshpass/sshpass
#   Apple Silicon Mac
#   ~25 GB free disk (one-time base image)

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VM_NAME="klava-ux-test"
BASE="ghcr.io/cirruslabs/macos-sequoia-base:latest"
VM_USER="admin"
VM_PASS="admin"
SSH_OPTS=(-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR \
          -o PreferredAuthentications=password -o PubkeyAuthentication=no -o IdentitiesOnly=yes \
          -o NumberOfPasswordPrompts=1)

command -v tart >/dev/null || { echo "ERROR: tart missing. brew install cirruslabs/cli/tart" >&2; exit 1; }
command -v sshpass >/dev/null || { echo "ERROR: sshpass missing. brew install hudochenkov/sshpass/sshpass" >&2; exit 1; }

vm_exists() {
    # tart list --format json returns spaces around colons, so we parse the
    # JSON properly rather than regex-matching.
    tart list --format json 2>/dev/null \
        | python3 -c "import json,sys; sys.exit(0 if any(v.get('Name')=='$VM_NAME' and v.get('Source')=='local' for v in json.load(sys.stdin)) else 1)"
}

MODE="rsync"
case "${1:-}" in
    --destroy)
        if vm_exists; then
            tart stop "$VM_NAME" 2>/dev/null || true
            tart delete "$VM_NAME"
            echo "✓ VM $VM_NAME destroyed"
        else
            echo "(no VM named $VM_NAME)"
        fi
        exit 0
        ;;
    --keep)   RESET=0 ;;
    --clone)  RESET=1; MODE="clone" ;;
    "")       RESET=1 ;;
    *)        echo "Unknown flag: $1" >&2; exit 2 ;;
esac

# Ensure base image is pulled (~20 GB first time)
if ! tart list 2>/dev/null | grep -q "macos-sequoia-base"; then
    echo "[0/6] Pulling base image (first time only, ~20 GB)..."
    tart pull "$BASE"
fi

if [ "$RESET" = 1 ] && vm_exists; then
    echo "[1/6] Destroying previous VM..."
    tart stop "$VM_NAME" 2>/dev/null || true
    tart delete "$VM_NAME"
fi

if ! vm_exists; then
    echo "[2/6] Cloning fresh VM from base..."
    tart clone "$BASE" "$VM_NAME"
fi

echo "[3/6] Booting VM (GUI window will appear)..."
# nohup + disown so the VM survives this script exiting. Otherwise the shell
# sends SIGHUP to `tart run` when the harness finishes and the VM stops.
nohup tart run "$VM_NAME" >"/tmp/tart-$VM_NAME.log" 2>&1 &
TART_PID=$!
disown $TART_PID 2>/dev/null || true
echo "   tart pid: $TART_PID (log: /tmp/tart-$VM_NAME.log)"

echo "[4/6] Waiting for SSH..."
IP=""
for i in $(seq 1 90); do
    IP=$(tart ip "$VM_NAME" 2>/dev/null || true)
    if [ -n "$IP" ] && sshpass -p "$VM_PASS" ssh "${SSH_OPTS[@]}" -o ConnectTimeout=2 "$VM_USER@$IP" true 2>/dev/null; then
        break
    fi
    sleep 2
done
[ -z "$IP" ] && { echo "ERROR: VM never got an IP after 180s" >&2; exit 1; }
echo "   VM IP: $IP"

if [ "$MODE" = "clone" ]; then
    echo "[5/6] Git cloning repo inside VM (simulating real new user)..."
    # No submodule init here — the vadimgest submodule is private and will fail
    # without gh auth, which the user sets up interactively inside the VM. That
    # failure path is itself what we want to observe.
    sshpass -p "$VM_PASS" ssh "${SSH_OPTS[@]}" "$VM_USER@$IP" bash <<'REMOTE'
        set -e
        cd ~
        rm -rf klava
        git clone https://github.com/VCasecnikovs/klava.git klava
        echo ""
        echo "✓ Repo cloned to ~/klava"
        echo "  Submodule NOT initialized (private, needs gh auth)"
REMOTE

    echo ""
    echo "=== VM ready for clone-path UX test ==="
    echo ""
    echo "  VM IP:        $IP"
    echo "  GUI window:   should already be visible"
    echo "  SSH:          sshpass -p $VM_PASS ssh ${SSH_OPTS[*]} $VM_USER@$IP"
    echo ""
    echo "Inside the VM (Terminal or SSH):"
    echo "  1. Authenticate GitHub for the private submodule:"
    echo "       brew install gh || curl -fsSL https://github.com/cli/cli/releases/download/v2.60.1/gh_2.60.1_macOS_arm64.zip -o gh.zip && ..."
    echo "       gh auth login        # choose HTTPS, paste token"
    echo "       gh auth setup-git"
    echo "  2. cd ~/klava && ./setup.sh"
    echo "  3. Open Safari → http://localhost:18788/dashboard"
    echo "  4. Click the wizard, try claude login, observe what breaks"
    echo ""
    echo "Stop & destroy when done:    ./scripts/test-setup-tart.sh --destroy"
    exit 0
fi

echo "[5/6] Syncing repo into VM (~/klava/)..."
# Include .git so setup.sh can auto-init the submodule from cached metadata
# (no network/SSH key needed for the vadimgest submodule).
sshpass -p "$VM_PASS" rsync -a \
    --checksum \
    --delete \
    --filter=':- .gitignore' \
    --exclude='node_modules' \
    --exclude='.venv' \
    --exclude='tools/dashboard/react-app/node_modules' \
    --exclude='tools/dashboard/react-app/dist' \
    -e "ssh ${SSH_OPTS[*]}" \
    "$REPO_DIR/" "$VM_USER@$IP:~/klava/"

echo "[6/6] Running setup.sh in VM..."
echo "-------------------------------------------------------------------"
sshpass -p "$VM_PASS" ssh "${SSH_OPTS[@]}" "$VM_USER@$IP" bash <<'REMOTE'
    set -e
    cd ~/klava
    # Simulate fresh clone: wipe vadimgest working tree so the submodule
    # auto-init path in setup.sh has something to do. .git/modules metadata
    # is preserved so no network fetch is needed.
    rm -rf vadimgest
    mkdir -p vadimgest
    ./setup.sh
REMOTE
SETUP_STATUS=$?
echo "-------------------------------------------------------------------"

if [ $SETUP_STATUS -ne 0 ]; then
    echo "✗ setup.sh failed inside VM (exit $SETUP_STATUS). Fix and re-run with --keep." >&2
    exit $SETUP_STATUS
fi

echo ""
echo "=== VM ready for UX testing ==="
echo ""
echo "  SSH in:       sshpass -p $VM_PASS ssh ${SSH_OPTS[*]} $VM_USER@$IP"
echo "  VM IP:        $IP"
echo "  GUI window:   should already be visible on your screen"
echo ""
echo "Next — inside the VM's GUI:"
echo "  1. Log in as admin (password: admin) if needed"
echo "  2. Open Terminal and run:"
echo "       for f in ~/Library/LaunchAgents/com.local.*.plist; do launchctl load \"\$f\"; done"
echo "  3. Open Safari → http://localhost:18788/dashboard"
echo "  4. Click through the setup wizard, try the vadimgest link, poke at everything"
echo ""
echo "When done:"
echo "  ./scripts/test-setup-tart.sh --destroy"
echo ""
echo "To iterate (edit code in host repo, re-sync + re-run setup.sh in VM):"
echo "  ./scripts/test-setup-tart.sh --keep"
