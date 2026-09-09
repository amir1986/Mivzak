#!/usr/bin/env bash
# Push the commit that starts the "Mivzak brief - primary" workflow in
# amir1986/mail-action- immediately.
#
# GitHub's cron scheduler starts scheduled runs on this account two to five
# hours late, so a Claude routine runs this script at 23:15 Israel time on
# trading days (Monday to Wednesday).  The workflow starts within seconds of
# the push because it listens for changes to the trigger log with the marker
# [mivzak-brief-run] in the commit message.
#
# Usage: push_mail_action_trigger.sh [--force]
#   Without --force the script does nothing outside Monday-Wednesday
#   23:05-23:55 Israel time (the routine also fires at other times because of
#   daylight-saving changes).  --force skips that check (manual tests).
set -euo pipefail

REPO_URL="https://github.com/amir1986/mail-action-"
CLONE_DIR="/home/user/mail-action-"
TRIGGER_FILE=".github/state/mivzak-brief-trigger.log"
COMMIT_MESSAGE="Run Mivzak brief [mivzak-brief-run]"
GIT_USER_NAME="amir1986"
GIT_USER_EMAIL="9213616+amir1986@users.noreply.github.com"

force="no"
if [[ "${1:-}" == "--force" ]]; then
  force="yes"
fi

weekday="$(TZ=Asia/Jerusalem date '+%u')"
clock="$(TZ=Asia/Jerusalem date '+%H:%M')"
stamp="$(TZ=Asia/Jerusalem date '+%Y-%m-%d %H:%M:%S %Z')"

if [[ "$force" == "no" ]]; then
  if [[ "$weekday" -gt 3 ]] || [[ "$clock" < "23:05" ]] || [[ "$clock" > "23:55" ]]; then
    echo "outside window, nothing done (Israel time $stamp, weekday $weekday)"
    exit 0
  fi
fi

if ! git -C "$CLONE_DIR" rev-parse HEAD >/dev/null 2>&1; then
  rm -rf "$CLONE_DIR"
  git clone --depth 1 "$REPO_URL" "$CLONE_DIR"
fi

git -C "$CLONE_DIR" fetch origin main
git -C "$CLONE_DIR" checkout -q -B main origin/main

suffix=""
if [[ "$force" == "yes" ]]; then
  suffix=" (forced)"
fi
echo "trigger ${stamp}${suffix}" >> "$CLONE_DIR/$TRIGGER_FILE"
git -C "$CLONE_DIR" add "$TRIGGER_FILE"
git -C "$CLONE_DIR" -c "user.name=$GIT_USER_NAME" -c "user.email=$GIT_USER_EMAIL" commit -q -m "$COMMIT_MESSAGE"

for attempt in 1 2 3; do
  # Capture the output so the exit status is git's own, not grep's.
  if output="$(git -C "$CLONE_DIR" push origin main 2>&1)"; then
    echo "trigger pushed $(git -C "$CLONE_DIR" rev-parse --short HEAD) at Israel time $stamp"
    exit 0
  fi
  printf '%s\n' "$output" | grep -v "push negotiation" >&2 || true
  echo "push attempt $attempt failed; rebasing and retrying"
  git -C "$CLONE_DIR" -c "user.name=$GIT_USER_NAME" -c "user.email=$GIT_USER_EMAIL" pull --rebase origin main
  sleep 5
done

echo "trigger push failed after 3 attempts" >&2
exit 1
