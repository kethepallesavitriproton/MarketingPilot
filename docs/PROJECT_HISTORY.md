# MarketingPilot — Project History and Current Status

**Last updated:** 2026-10-19  
**Project stage:** Local MVP / development prototype  
**Primary aim:** Help a solo marketer or small business organize marketing work for clients, create campaign content, get approval, publish approved social posts, and review available results.

This document records what has been implemented, what has been tried successfully, the key product decisions made during development, and the work that remains. The vision and broader roadmap remain in [MarketingPilot_Vision.md](MarketingPilot_Vision.md); Meta-specific setup is in [META_PUBLISHING_SETUP.md](META_PUBLISHING_SETUP.md).

## Product direction agreed so far

- MarketingPilot is being built page by page and in small implementation batches, while keeping the agreed roadmap in view.
- The first use is a local tool for the developer/marketer to serve clients. It is not yet a hosted customer-facing SaaS product.
- Client businesses own their Facebook Pages, Instagram accounts, ad accounts, audiences, and advertising spend. MarketingPilot uses a client's connection only for that client.
- Generated creative files are ordinary image files that can be downloaded and used on different platforms. Direct publishing depends on each platform's supported API and account permissions.
- Content must be reviewed and approved before publishing. A publish action is explicit; connecting an account does not publish anything.
- Facebook Lead Ads forms are created in the client's Meta account. MarketingPilot's campaign brief records the form setup requirements; it does not create the form or run paid ads.
- Paid-ad budgets and targeting details in MarketingPilot are planning information. The app does not spend money, create or launch ads, or guarantee results.
- New ideas are added to the MVP plan when they improve the product. The vision document is kept for product requirements and roadmap items, not as a transcript of every question or discussion.
- The initial stack is Python, FastAPI, SQLite, HTML/CSS, and official platform APIs where available. Ollama was considered for optional AI drafting, but no AI provider was selected or implemented.

## Implemented application areas

### Workspace and client records

- Local dashboard and responsive navigation for Overview, Campaigns, Image Studio, Content Planner, Calendar, Leads, Reports, and Connections.
- Client/business records include business name, niche, contact information, notes, brand colors, brand voice, and reusable products/services details.
- Data is stored in the local `marketingpilot.db` SQLite file.

### Campaigns, audiences, and approval

- Campaign briefs capture goal, platform, audience, location, offer, and status.
- Audience details include customer type, interests or intent, needs, exclusions, and location.
- Paid-ad planning fields include proposed budget and period, dates, destination, call to action, Meta Instant Form fields, privacy-policy URL, thank-you message, verification plans, and client approval state.
- Changes to approval-sensitive setup details require renewed approval.
- Campaigns can group related posts, leads, and manually entered report metrics.
- Five weekday draft starters can be prepared from campaign and client information using a rule-based workflow.

### Content and creative workflow

- Draft posts can be created for Facebook, Instagram, WhatsApp Status, and Google Ads.
- Posts can include a campaign, scheduled date/time, image, caption, and status such as Draft, Needs approval, Approved, Scheduled, or Published.
- Approved or scheduled posts return to review when important content changes; client feedback is stored with the content and stale feedback clears after content changes.
- Existing images and copy can be reused to create channel-specific drafts. One Image Studio creative can be used to prepare drafts for several channels.
- Image Studio uses client brand information and can incorporate products/services and campaign goal, offer, audience context, and call to action.
- Generated creatives can use square, vertical, or landscape formats and can be downloaded as regular PNG images.
- A print-ready campaign review packet can be prepared for client review.
- The calendar shows planned content and can export it as an `.ics` calendar file, for all clients or one client. Planned local times are included when provided.
- The dashboard shows reminders for overdue or near-term planned posts.

### Meta connection and publishing

- The Meta developer app was configured with the Facebook Login flow and the relevant Facebook publishing and Instagram API use case/permissions for development.
- Connections are stored per client. A client authorizes Meta, selects an eligible Facebook Page, and MarketingPilot stores its Page token encrypted with the local Fernet key.
- When Instagram is enabled, MarketingPilot can discover the professional Instagram account linked to the selected Page.
- The Instagram account must be a Business or Creator account linked to the client's Facebook Page for this Facebook Login integration. Creator accounts are professional accounts used by individual creators/owners.
- The developer account was added to the Meta app as an administrator. Meta's app-role form rejected adding the developer as another app user because the person already owned the app; the existing administrator role was sufficient for development.
- A reachable HTTPS callback is required for Meta authorization. A local HTTP callback was rejected by Meta. The local prototype also requires its workspace password gate before Meta authorization can be used through a temporary HTTPS tunnel.
- Approved Facebook Page text posts and image posts can be published with an explicit **Publish to Facebook** action.
- Approved single-image Instagram feed posts can be published with an explicit **Publish to Instagram** action. The app prepares a compatible image, and Meta fetches it through the app's public HTTPS address.
- Publishing state, platform post/media IDs, URLs, and timestamps are recorded. Uncertain publishing responses are locked for manual checking to reduce duplicate posts.
- The user confirmed successful Facebook text/image publishing and successful Instagram image publishing. Posts that were later deleted manually on Facebook remain external deletions; MarketingPilot does not mirror deletions back from Meta.
- Published Facebook posts can now refresh current reactions, comments, and shares. Published Instagram posts can refresh current likes and comments. Counts and last-checked time are shown in the Content Planner.
- Engagement refresh is a per-post manual action. It is not historical reporting and does not provide reach, clicks, leads, or ad spend.

### Leads and reporting

- Leads can be imported from Meta CSV exports; exact duplicate Meta lead IDs are skipped.
- Leads can be filtered, exported, assigned follow-up dates, and tracked through statuses. The dashboard shows follow-ups due soon or overdue.
- Lead details should remain sample/test data in this local prototype. A live secure lead integration and privacy controls are not implemented.
- Reports support manual entry and CSV import/export of daily reach, clicks, leads, spend, and notes, with duplicate rows skipped.
- Reports can calculate click rate, cost per click, and cost per lead from the entered figures.
- Filtered print-friendly performance summaries include daily reach, click, and lead trends and can be saved as PDF from the browser.
- Current Meta engagement counts are shown on the content item; they are not yet included as historical rows in the campaign reports.

## User-confirmed setup and operating notes

- The app has been started on Windows with `run_windows.bat` and is accessed locally in a browser.
- The user has configured Meta app credentials and a token-encryption key in the private local `.env` file. Secret values are intentionally not copied into this document.
- The Meta HTTPS callback and workspace password gate were configured for development authorization.
- The user linked an Instagram Creator account to the Facebook Page and reconnected the Page in MarketingPilot. Instagram publishing then succeeded.
- The user can leave the Windows development server running while making code changes when Uvicorn's `--reload` mode is active; if reload does not occur, restart the batch file. Restart after changing `.env` settings so the app reads those values again.
- Generated post images are stored in the project and should be backed up with the database when preserving local work.

## Not implemented yet

- WhatsApp Status publishing through an official supported API.
- Direct Google Ads account connection or reporting.
- Creation, scheduling, funding, or launch of paid campaigns and Meta Instant Forms.
- Automatic publishing at a scheduled time. The current scheduled status/calendar represents a plan; the user must use the explicit publish action.
- Automatic Facebook/Instagram reach or historical insights, ad metrics, or campaign performance synchronization.
- Live Meta lead form/webhook sync, real-time lead delivery, or automatic phone/email verification.
- AI caption generation or image generation through Ollama or a cloud model.
- Production-grade multi-user login, client data isolation, audit logging, reliable hosting, backups, and full privacy/security controls.
- App Review/permission approval needed to support customers outside the developer/tester roles. Development success with the owner's account does not itself establish production access.

## Next work, in practical order

1. Continue verifying the new Meta engagement refresh against the connected developer Page and Instagram account.
2. Decide which Meta reach or account insights are useful, then identify and enable only the required permissions before implementing history/report integration.
3. Plan a secure hosted deployment and proper user/client access before allowing clients to use the application directly.
4. Add live lead sync only after secure hosting, consent, storage controls, and a delivery/verification provider are ready.
5. Investigate Google Ads reporting and WhatsApp capabilities when account access and API requirements are clear.
6. Consider AI drafting after selecting a provider/runtime with acceptable costs, privacy, and computer requirements.

## Local files to know

- `app.py` — FastAPI application, database setup, workflows, and platform integrations.
- `templates/` — HTML pages for the application.
- `static/style.css` — application styling.
- `marketingpilot.db` — local SQLite data; back up before moving or deleting the project.
- `.env` — local private settings and credentials; do not share or commit it.
- `.env.example` — names of supported settings without private values.
- `run_windows.bat` — Windows setup and development startup.
- `README.md` — quick start, current features, and important limitations.
- `docs/MarketingPilot_Vision.md` — product vision, roadmap, and business direction.
- `docs/META_PUBLISHING_SETUP.md` — Meta app configuration and publishing checklist.

