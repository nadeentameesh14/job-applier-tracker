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

echo "1/5 Installing the helper's Python packages (in $VENV)..."
mkdir -p "$HOME_DIR"
python3 -m venv "$VENV"
"$VENV/bin/pip" install -q --upgrade pip
"$VENV/bin/pip" install -q -r "$REPO/requirements.txt" playwright

echo "2/5 Getting a browser for it..."
if [ -d "/Applications/Google Chrome.app" ]; then
  echo "   Using your Google Chrome."
else
  "$VENV/bin/python" -m playwright install chromium
fi

echo "3/5 Making it start when you log in, and every day at 9am..."
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

echo "4/5 Setting up Claude Code (it answers form questions from your CV, on your Claude subscription)..."
export PATH="$HOME/.local/bin:$PATH"
if ! command -v claude >/dev/null; then
  curl -fsSL https://claude.ai/install.sh | bash
fi
if claude -p "Reply with the word OK" --model haiku >/dev/null 2>&1; then
  echo "   Claude Code is signed in."
else
  echo "   Claude Code needs you to sign in once. It will open now: sign in with your Claude account in the"
  echo "   browser, then type /exit and press Enter to come back here."
  read -r -p "   Press Enter to start..." _
  claude || true
fi

echo "5/5 Opening a browser window: sign in to LinkedIn there once, then close it."
cd "$REPO" && "$VENV/bin/python" -m jobapplier.helper --repo "$REPO" --login

echo
echo "All set. Each morning (or when you log in) an approval page opens with that day's Easy Apply jobs."
echo "Try a safe test now (fills the forms but doesn't submit):"
echo "   cd \"$REPO\" && \"$VENV/bin/python\" -m jobapplier.helper --test"
echo "Log file: $HOME_DIR/helper.log   To stop it starting automatically: launchctl unload \"$PLIST\""
