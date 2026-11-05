#!/bin/bash
# One-time setup of the laptop helper on a Mac. Run it from inside your PRIVATE repo folder:
#   bash helper/install_mac.sh
# It installs what the helper needs, makes it start when you log in (and at 9am), and opens a
# browser window so you can sign in to LinkedIn once.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
HOME_DIR="$HOME/.job-applier"
VENV="$HOME_DIR/venv"
PLIST="$HOME/Library/LaunchAgents/com.jobapplier.helper.plist"

command -v python3 >/dev/null || { echo "Please install Python 3 from https://www.python.org/downloads/ and run this again."; exit 1; }
python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))' || { echo "Your Python is too old. Install Python 3.12 from https://www.python.org/downloads/macos/ and run this again."; exit 1; }
command -v git >/dev/null || { echo "Please install git (run: xcode-select --install) and run this again."; exit 1; }

echo "1/4 Installing the helper's Python packages (in $VENV)..."
mkdir -p "$HOME_DIR"
python3 -m venv "$VENV"
"$VENV/bin/pip" install -q --upgrade pip
"$VENV/bin/pip" install -q -r "$REPO/requirements.txt" playwright

echo "2/4 Getting a browser for it..."
if [ -d "/Applications/Google Chrome.app" ]; then
  echo "   Using your Google Chrome."
else
  "$VENV/bin/python" -m playwright install chromium
fi

echo "3/4 Making it start when you log in, and every day at 9am..."
cat > "$HOME_DIR/run.sh" <<EOF
#!/bin/bash
cd "$REPO" && "$VENV/bin/python" -m jobapplier.helper --repo "$REPO" >> "$HOME_DIR/helper.log" 2>&1
EOF
chmod +x "$HOME_DIR/run.sh"
mkdir -p "$(dirname "$PLIST")"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.jobapplier.helper</string>
  <key>ProgramArguments</key><array><string>$HOME_DIR/run.sh</string></array>
  <key>RunAtLoad</key><true/>
  <key>StartCalendarInterval</key><dict><key>Hour</key><integer>9</integer><key>Minute</key><integer>0</integer></dict>
  <key>EnvironmentVariables</key><dict><key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string></dict>
</dict></plist>
EOF
launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"

echo "4/4 Opening a browser window: sign in to LinkedIn there once, then close it."
cd "$REPO" && "$VENV/bin/python" -m jobapplier.helper --repo "$REPO" --login

echo
echo "All set. Each morning (or when you log in) an approval page opens with that day's Easy Apply jobs."
echo "Try a safe test now (fills the forms but doesn't submit):"
echo "   cd \"$REPO\" && \"$VENV/bin/python\" -m jobapplier.helper --test"
echo "Log file: $HOME_DIR/helper.log   To stop it starting automatically: launchctl unload \"$PLIST\""
