#!/usr/bin/env bash
# Install a "Send to ShotClassify" Quick Action on macOS.
#
# What this does:
#   1. Drops a shell script into ~/Library/Application Support/ShotClassify/
#      which POSTs the selected file to your local ShotClassify API.
#   2. Opens the .shortcut bundle so you can confirm the install in Shortcuts.app.
#
# Requirements:
#   - macOS 13+ with Shortcuts.app
#   - shotclassify API running on http://127.0.0.1:7441
#   - SHOTCLASSIFY_API_KEY exported in your shell

set -euo pipefail

API="${SHOTCLASSIFY_API:-http://127.0.0.1:7441}"
KEY="${SHOTCLASSIFY_API_KEY:-}"
SUPPORT="$HOME/Library/Application Support/ShotClassify"
mkdir -p "$SUPPORT"

cat > "$SUPPORT/send.sh" <<EOF
#!/usr/bin/env bash
set -euo pipefail
API="\${SHOTCLASSIFY_API:-$API}"
KEY="\${SHOTCLASSIFY_API_KEY:-$KEY}"
for f in "\$@"; do
  curl -fsS -X POST "\$API/v1/classify" \\
    -H "X-API-Key: \$KEY" \\
    -F "file=@\$f" \\
    -F "note=via macOS Shortcut" \\
    | tee -a "\$HOME/Library/Logs/shotclassify.log"
done
osascript -e 'display notification "ShotClassify finished" with title "ShotClassify"'
EOF
chmod +x "$SUPPORT/send.sh"

SHORTCUT="$(cd "$(dirname "$0")" && pwd)/SendToShotClassify.shortcut"
if [ -f "$SHORTCUT" ]; then
  open "$SHORTCUT"
else
  echo "Shortcut bundle not found at $SHORTCUT"
  echo "You can still trigger ShotClassify with:"
  echo "  \"$SUPPORT/send.sh\" ~/Desktop/your-shot.png"
fi
echo "Installed helper: $SUPPORT/send.sh"
