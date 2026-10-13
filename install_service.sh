#!/bin/zsh
# Runs Genius Tagger in the background at http://localhost:8765, starting at login.
# Run again after changing the code. Uninstall: ./install_service.sh --remove
set -e
LABEL=com.genius-tagger
PLIST=~/Library/LaunchAgents/$LABEL.plist
SRC=${0:A:h}
# Background services can't read ~/Documents, so run from a copy outside it.
DIR="$HOME/Library/Application Support/Genius Tagger"

launchctl bootout gui/$(id -u)/$LABEL 2>/dev/null || true
if [[ $1 == --remove ]]; then rm -f $PLIST; rm -rf "$DIR"; echo "Removed."; exit; fi

mkdir -p ~/Library/LaunchAgents ~/Library/Logs "$DIR"
cp "$SRC"/{app.py,genius_tag.py,youtube.py,ui.html} "$DIR/"
cat > $PLIST <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array><string>/usr/bin/python3</string><string>$DIR/app.py</string></array>
  <key>WorkingDirectory</key><string>$DIR</string>
  <key>EnvironmentVariables</key><dict><key>TAGGER_SERVICE</key><string>1</string></dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>2</integer>
  <key>StandardOutPath</key><string>$HOME/Library/Logs/genius-tagger.log</string>
  <key>StandardErrorPath</key><string>$HOME/Library/Logs/genius-tagger.log</string>
</dict>
</plist>
PLIST
launchctl bootstrap gui/$(id -u) $PLIST
echo "Genius Tagger is running at http://localhost:8765"
