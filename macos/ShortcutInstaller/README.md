# Send to ShotClassify (macOS Quick Action)

Adds a Finder / Share-sheet action that POSTs any selected image to your local ShotClassify API.

## Install

```
export SHOTCLASSIFY_API=http://127.0.0.1:7441
export SHOTCLASSIFY_API_KEY=$(grep AUTH_API_KEY ../../.env | cut -d= -f2)
bash install.sh
```

This drops a shell helper into `~/Library/Application Support/ShotClassify/send.sh` and opens the .shortcut bundle so you can confirm install in the Shortcuts app.

## Manual run

```
~/Library/Application\ Support/ShotClassify/send.sh ~/Desktop/screenshot.png
```

The response (full JSON classification) is appended to `~/Library/Logs/shotclassify.log`.
