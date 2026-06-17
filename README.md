# Travel Status Notifier

Automatically monitors your American Airlines and Marriott Bonvoy accounts and emails your wife whenever your travel status changes — flight delayed, boarding, departed, landed, gate changed, or hotel check-in day.

## How it works

1. Logs into AA and Marriott using an automated browser (Playwright)
2. Checks flight status every 5 minutes (configurable)
3. Emails your wife only when something changes
4. Includes your approximate location (city/region from your IP) in every message

## Setup (Mac)

### 1. Prerequisites

```bash
# Python 3.11+ (check version)
python3 --version

# Install via Homebrew if needed
brew install python@3.11
```

### 2. Clone and set up environment

```bash
cd Testing
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

### 3. Configure credentials

```bash
cp .env.example .env
open -e .env   # Opens in TextEdit
```

Fill in `.env`:

| Variable | Description |
|---|---|
| `AA_USERNAME` | Your AA login email |
| `AA_PASSWORD` | Your AA password |
| `MARRIOTT_USERNAME` | Your Marriott login email |
| `MARRIOTT_PASSWORD` | Your Marriott password |
| `GMAIL_SENDER` | Your Gmail address |
| `GMAIL_APP_PASSWORD` | 16-char App Password (see below) |
| `NOTIFY_EMAIL` | Your wife's email address |

**Gmail App Password:** Go to [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords), create a new app called "Travel Notifier", and paste the generated 16-character password into `.env`. You must have 2-Step Verification enabled on your Google account.

### 4. First run (headed mode)

Keep `HEADED_BROWSER=True` in `.env` for the first run. This opens a visible browser window so you can:
- Watch the login complete
- Solve any CAPTCHA manually
- Enter MFA codes when prompted in the terminal

```bash
python3 -m travel_notifier.main
```

### 5. Headless mode (after first login)

Once cookies are saved, switch to headless for background operation:

```bash
# Edit .env: set HEADED_BROWSER=False
python3 -m travel_notifier.main
```

### 6. Run in the background (Mac launchd)

Create `~/Library/LaunchAgents/com.travel_notifier.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
    "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.travel_notifier</string>
  <key>ProgramArguments</key>
  <array>
    <string>/path/to/Testing/.venv/bin/python3</string>
    <string>-m</string>
    <string>travel_notifier.main</string>
  </array>
  <key>WorkingDirectory</key>
  <string>/path/to/Testing</string>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>/Users/YOU/.travel_notifier_launchd.log</string>
  <key>StandardErrorPath</key>
  <string>/Users/YOU/.travel_notifier_launchd.log</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>/usr/local/bin:/usr/bin:/bin</string>
  </dict>
</dict>
</plist>
```

Replace `/path/to/Testing` and `/Users/YOU` with your actual paths, then:

```bash
launchctl load ~/Library/LaunchAgents/com.travel_notifier.plist
```

## Email notifications

| Event | Subject |
|---|---|
| Flight delayed | `✈ AA 1234 to LAX is DELAYED` |
| Now boarding | `✈ AA 1234 — NOW BOARDING at Gate B22` |
| Departed | `✈ AA 1234 has DEPARTED DFW` |
| Landed | `✈ AA 1234 has LANDED in LAX` |
| Cancelled | `❌ AA 1234 has been CANCELLED` |
| Gate change | `✈ AA 1234 — Gate changed to C15` |
| Hotel check-in | `🏨 Check-in day: Marriott Marquis Dallas` |

Each email includes a flight/stay summary card and your current approximate location.

## Monitoring

```bash
# Live log
tail -f ~/.travel_notifier.log

# Current state (flights + hotels + sent notifications)
cat ~/.travel_notifier_state.json | python3 -m json.tool
```

## Testing without travel

To test that emails work without waiting for a real status change:

1. Let the app run one poll cycle (it saves state)
2. Open `~/.travel_notifier_state.json`
3. Change a flight's `"status"` value (e.g. `"On Time"` → `"Delayed"`)
4. Save the file and wait for the next poll — an email should arrive within 5 minutes

## Troubleshooting

**Login fails / CAPTCHA loops:** Run with `HEADED_BROWSER=True` so you can interact manually.  
**MFA code not arriving:** Ensure your AA/Marriott accounts have a verified phone number or email for MFA.  
**No flights showing:** The app only tracks upcoming flights. Check that you have active reservations in your AA account.  
**Gmail authentication error:** Confirm you are using an App Password (not your Gmail password) and that 2-Step Verification is enabled.
