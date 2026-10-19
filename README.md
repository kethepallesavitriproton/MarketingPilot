# MarketingPilot MVP

A zero-cost local prototype for organizing clients, social content drafts, approvals, and campaign metrics.

For the implementation history, user-confirmed setup, current limitations, and next work, see [the project history](docs/PROJECT_HISTORY.md).

## Features
- Client list stored in local SQLite database
- Content drafts for Instagram, Facebook, WhatsApp Status, and Google Ads
- Reuse a client’s generated image across multiple channel drafts
- Download generated creatives as standard 1080×1080 PNG files for platform upload
- Create a new channel draft by reusing an existing post’s image and copy
- Draft / approval / scheduled status tracking
- Changes to approved or scheduled content send it back for client approval
- Record client decisions and review notes on each campaign content item; stale notes clear when the content changes
- Create five editable weekday draft starters using the campaign audience, needs, interests, location, goal, and the client’s saved brand voice
- Store client products and services in the reusable business profile and include them in draft starters
- Insert a client’s saved products and services into Image Studio’s supporting message for branded campaign graphics
- Use the selected campaign’s goal, offer, audience context, and call to action while preparing a creative
- Create channel-specific draft entries for several platforms from one shared Image Studio graphic
- Choose square, vertical, or landscape dimensions for generated campaign graphics and preserve them when downloading PNGs
- Save proposed ad budget, run dates, destination, CTA, Meta Instant Form fields, privacy link, thank-you message, phone/email verification plan, and client approval status in each campaign brief
- Build a structured audience brief with customer type, interests or intent, needs, exclusions, and location; targeting changes reset client approval
- Prepare a print-ready campaign and content review packet for clients
- Export planned content schedules as a calendar file, for all clients or one client
- Set optional local posting times and include them in the calendar and calendar-file export
- Overview reminders for overdue posts and items due within three days
- Manual campaign metrics and basic aggregate reporting
- Import daily performance metrics from the provided CSV template; exact duplicate rows are skipped
- Prepare a filtered, print-friendly campaign performance summary for client review or browser PDF saving
- Show daily reach, clicks, and lead trends on client performance summaries
- Calculate click rate, cost per click, and cost per lead from entered campaign results
- Meta lead CSV import/export and follow-up status tracking
- Schedule lead follow-up dates, see due reminders on the overview, and include them in exports
- Responsive dashboard
- Central Connections page showing platform setup readiness and separate client authorization status
- Per-client Meta OAuth connection and Facebook Page selection; Page tokens are encrypted locally
- Refresh Facebook reactions, comments, and shares, or Instagram likes and comments, for posts published through MarketingPilot

## Requirements
- Python 3.10 or newer
- Internet connection for the initial package installation

## Windows quick start
1. Extract this folder to a location you can write to.
2. Double-click `run_windows.bat`.
3. Wait for package installation and for Uvicorn to start.
4. Open `http://127.0.0.1:8000` in your browser.
5. Keep the terminal window open while using the app.

Meta connection is optional. To use it locally, first complete the private
`.env` setup in [the Meta publishing checklist](docs/META_PUBLISHING_SETUP.md).

If `py` is not recognized, install Python from https://www.python.org/downloads/ and enable the option to add Python to PATH, then run the batch file again.

## Manual start
```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m uvicorn app:app --reload
```

## Important limitations
- This is an early local MVP, not production-ready multi-user software.
- Data is stored in `marketingpilot.db` in this folder. Back it up before moving or deleting the folder.
- Approved Facebook Page posts with a caption and optional generated image can be published through an explicit action after that client's Page is connected. Approved single-image Instagram feed posts are supported after Instagram is enabled in Meta settings and the client's professional account is linked to its Page. WhatsApp Status, Google Ads, and paid-ad campaigns are not launched directly yet.
- Campaign budget, schedule, destination, and approval fields are a planning record only; no money is spent and no ad is launched.
- Reach, clicks, leads, and ad spend remain manual report entries. The content planner can refresh current organic engagement totals for posts MarketingPilot published to Facebook or Instagram; these counts do not include reach or ad performance.
- Leads are imported manually from Meta CSV exports; there is no live API or webhook connection yet. Do not enter real customer contact details in this local prototype.
- Meta authorization connects each client's Facebook Page and can retrieve its linked Instagram professional account when Instagram publishing is enabled. Connecting an account does not publish anything.
- Meta credentials and the token-encryption key are read from a local `.env` file. Keep it private and back up the encryption key securely; losing it makes stored Page tokens unreadable.
- Meta OAuth requires a reachable HTTPS callback. The local HTTP address is not sufficient. The optional workspace password gate must be enabled before temporarily exposing the prototype through a tunnel.
- Instant Form fields in campaign briefs are a setup checklist; create the actual form in the client’s Meta ad account.
- Verification choices in campaign briefs are planning notes only; code delivery and contact verification need a live lead connection, secure hosting, and configured SMS/email providers.
- Do not store passwords, unencrypted access tokens, payment information, or real lead contact details in this local prototype.
- Before hosting publicly, add authentication, CSRF protection, validation, secure secrets handling, backups, and appropriate privacy controls.

## Suggested next steps
1. Review the connected Meta app's permissions and complete any Meta review needed for customer accounts.
2. Decide whether to add supported Meta reach and account insights, then connect the required permissions.
3. Plan a secure hosted version before inviting clients to use the workspace directly.
4. Add Google Ads reporting after the client authorization and API requirements are understood.
