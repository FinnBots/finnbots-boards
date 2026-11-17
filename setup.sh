#!/usr/bin/env bash
# setup.sh — create FinnBots/finnbots-boards and start the cloud leaderboards (2026-11-17). Run ONCE, from this folder.
# Security review: factory/SECURITY-REVIEW-BOARDS.md. Idempotent: every step checks before it acts.
#   1. seed state/ from the Mac (holding the scanner's own lock, so no scan is half-written while it is copied)
#   2. create the PUBLIC repo, push, turn on GitHub Pages
#   3. a READ-ONLY deploy key on the private scanner repo; its private half goes straight into the boards repo's
#      Actions secret SCANNER_READ_KEY through stdin and is then deleted — never printed, never kept on disk
#   4. run the workflow once and show the result
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; cd "$HERE"
FB_ROOT="$(cd "$HERE/../.." && pwd)"; SCANNER="$FB_ROOT/scanner/FinnBots Games"; REPO=FinnBots/finnbots-boards
gh auth status >/dev/null 2>&1 || { echo "gh is not signed in (gh auth login)"; exit 1; }

echo "1. seed the state from the Mac's scanner (under its lock)"
/opt/anaconda3/bin/python3 - "$FB_ROOT" "$HERE" <<'PY'
import fcntl, os, shutil, sys, glob
fb, here = sys.argv[1], sys.argv[2]
lock = open(os.path.join(fb, "scan-state", "scanner.lock"), "w")
fcntl.flock(lock, fcntl.LOCK_EX)                     # wait for any running scan to finish
st, lb, out = os.path.join(here, "state"), os.path.join(here, "state", "leaderboards"), os.path.join(here, "boards")
for d in (lb, os.path.join(st, "inputs"), out): os.makedirs(d, exist_ok=True)
shutil.copy2(os.path.expanduser("~/Desktop/checkpoint_treasury_prod.txt"), st)
for f in glob.glob(os.path.join(fb, "leaderboards", "*")):
    if os.path.isfile(f): shutil.copy2(f, lb)
shutil.copy2(os.path.expanduser("~/pick-a-bot-deploy/bots.json"), os.path.join(st, "inputs"))
shutil.copy2(os.path.join(fb, "deploy", "spot-a-finnbot", "bot_traits.json"), os.path.join(st, "inputs"))
import re
for f in os.listdir(lb):
    if re.match(r"^(leaderboard_[a-z0-9]+\.csv|cabinet_names\.csv|build_funds\.json)$", f): shutil.copy2(os.path.join(lb, f), out)
print("   seeded:", len(os.listdir(lb)), "board-state files ·", len(os.listdir(out)), "published files")
PY

echo "2. the public repo + Pages"
[ -d .git ] || { git init -q -b main; }
git add -A && { git diff --cached --quiet || git commit -q -m "FinnBots leaderboards, published from the cloud (seeded from the Mac scanner)"; }
gh repo view "$REPO" >/dev/null 2>&1 || gh repo create "$REPO" --public --description "FinnBots leaderboards — published from the chain every 15 minutes" >/dev/null
git remote get-url origin >/dev/null 2>&1 || git remote add origin "https://github.com/$REPO.git"
git push -q -u origin main
gh api "repos/$REPO/pages" >/dev/null 2>&1 || gh api -X POST "repos/$REPO/pages" -f "source[branch]=main" -f "source[path]=/" >/dev/null
echo "   https://finnbots.github.io/finnbots-boards/boards/"

echo "3. read-only scanner key (never printed)"
if ! gh secret list -R "$REPO" 2>/dev/null | grep -q SCANNER_READ_KEY; then
  K="$(mktemp -d)"; trap 'rm -rf "$K"' EXIT
  ssh-keygen -q -t ed25519 -N "" -C "finnbots-boards (read-only)" -f "$K/key"
  gh repo deploy-key add "$K/key.pub" -R FinnBots/finnbots-scanner --title "finnbots-boards cloud scan (read-only)" >/dev/null
  gh secret set SCANNER_READ_KEY -R "$REPO" < "$K/key"
  rm -rf "$K"; echo "   deploy key added (read-only) and stored as the Actions secret"
fi

echo "4. first run"
gh workflow run scan.yml -R "$REPO" && sleep 8
gh run list -R "$REPO" --workflow scan.yml --limit 1
echo "Watch it: gh run watch -R $REPO   ·   then tell Claude it ran."
