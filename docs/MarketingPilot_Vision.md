# MarketingPilot --- Vision and Project Plan

**Project status:** Early MVP / local prototype\
**Budget target:** \$0 to begin\
**Primary goal:** Build a practical digital-marketing workflow that can
serve real clients first, then gradually become a reusable automation
product.

## 1. Our vision

MarketingPilot aims to help small businesses plan, create, organize,
publish, capture inquiries, and measure digital marketing from one
simple workspace.

We want to reduce repetitive marketing work---not promise guaranteed
sales or replace human judgment. The system should make it easier for a
small business or a solo marketer to manage content consistently across:

-   Instagram
-   Facebook
-   WhatsApp Status
-   Google Ads

Our long-term direction is to combine a client-service business with a
software product. Initially, we can use MarketingPilot internally to
deliver marketing services. As we learn what clients need, we can turn
the most useful repeatable workflows into product features.

## 2. The problem we want to solve

Small businesses may struggle to post consistently, write effective
captions, plan campaigns, keep track of client approvals, and understand
performance reports. Marketing work is often scattered across
spreadsheets, design tools, social platforms, and ad dashboards.

MarketingPilot should bring the routine parts of that workflow into one
place while keeping business owners in control of their content,
budgets, and public-facing changes.

## 3. Who it is for

Our initial target customers are small businesses and solo marketers,
for example:

-   Clothing and retail shops
-   Salons and beauty businesses
-   Restaurants and cafés
-   Local service providers
-   Small product brands

We should begin with one niche rather than trying to serve every type of
business at once.

## 4. Product principles

1.  **Start at zero cost:** Use free tools and run locally during
    development wherever practical.
2.  **Deliver value early:** Build a useful workflow before adding
    complex integrations.
3.  **Human approval first:** Drafts must be reviewed before publishing.
    Campaign budget changes and other consequential actions should
    require explicit authorization.
4.  **Use official integrations:** Connect to platforms through their
    official APIs and permitted methods.
5.  **Protect client information:** Store credentials securely, limit
    access, and never expose API keys or access tokens in source code or
    public repositories.
6.  **Client-owned ad accounts:** Clients own their platform accounts,
    audiences, and spend. MarketingPilot uses only authorized access.
    Configure each platform connection once for a client and reuse it
    across that client's workflows; never share it with other clients.
7.  **Measure real outcomes:** Report available metrics accurately. Do
    not invent results or promise guaranteed reach, leads, or sales.
8.  **Automate gradually:** First make the process work manually, then
    automate the repeated steps.
9.  **Keep the system understandable:** Prefer small, testable features
    over unnecessary complexity.

## 5. Roadmap

### Phase 1 --- Local MVP

-   Run the app on the developer's desktop.
-   Manage client/business records.
-   Create and store social post drafts.
-   Create WhatsApp Status drafts alongside other social content; posting
    remains manual until a supported official publishing method is
    available.
-   Save client brand colors and voice; create simple branded campaign
    graphics, save them with draft posts for client review, and download
    them as standard PNG files for upload to supported platforms.
-   Reuse a client's generated image across channel-specific content
    drafts; create a new channel draft from an existing post while
    keeping each caption and schedule editable per channel.
-   Organize a content calendar.
-   Store an optional local publishing time with each post, show it in the
    calendar, and include timed events in calendar exports.
-   Track draft, approval, and planned-publishing statuses.
-   Record campaign metrics and create simple reports.
-   Calculate click rate, cost per click, and cost per lead from manually
    recorded results, while clearly distinguishing these estimates from
    platform-reported values.
-   Save a brief for each campaign with its goal, channel, audience,
    location, and offer; link content and recorded results to that brief.
-   Record a proposed ad budget and period, run dates, destination,
    call to action, Instant Form contact fields, privacy-policy link,
    thank-you message, phone/email verification plan, and whether the
    client approved those setup details.
    These are planning fields only; they do not create, fund, or launch ads.
-   Import Meta Instant Form leads from CSV exports and track follow-up
    status and dates.
-   Export content or reports when useful.
-   Import manually exported platform results through a standard CSV
    template, with duplicate rows skipped.
-   Prepare filtered, print-friendly performance summaries for client
    review or saving as a PDF from the browser.
-   Show daily reach, click, and lead trends in performance summaries.

**Success condition:** A complete sample campaign can be managed locally
from client details to a basic report.

### Phase 2 --- Content workflow automation

-   Create five editable weekday draft starters from a campaign brief
    using its audience needs, interests, customer type, location, and goal
    with the client's saved brand voice in a no-cost, rule-based workflow.
-   Offer optional AI-assisted copy and image drafting. Support a local
    Ollama runtime when the user has installed and started it with compatible
    models; consider a cloud provider only after reviewing cost and privacy.
-   Draft captions, calls to action, and creative briefs.
-   Reuse brand voice and product details.
-   Store a reusable products-and-services summary on each client profile
    and include it in campaign draft starters.
-   Let Image Studio insert a client’s saved products and services into a
    supporting message for branded campaign graphics.
-   Carry the selected campaign’s goal, offer, audience context, and call
    to action into Image Studio so creatives can be tailored to the campaign.
-   Create draft entries for multiple selected channels from one Image
    Studio graphic, while keeping all entries in draft for review.
-   Offer square, vertical, and landscape campaign graphic formats and
    preserve the selected dimensions in PNG downloads.
-   Build audience briefs from customer type, interests or intent, needs,
    exclusions, and location for the client or marketer to apply in the ad
    platform. Changes to targeting details require renewed client approval.
-   Add client review and approval steps.
-   Record per-content-item client feedback and clear stale feedback when
    the content itself is changed; save the decision and note directly from
    the campaign overview after the client review.
-   Return approved or scheduled content to review if its caption,
    creative, channel, campaign, or date changes.
-   Prepare a print-ready client review packet with campaign setup,
    scheduled content, captions, and creatives; record client decisions
    in the workspace after review.
-   Carry the approved campaign setup into a future ad workflow and ask
    for renewed approval if its client, goal, offer, audience, channel,
    location, budget, schedule, destination, or call to action changes.
-   Show in-app reminders for overdue and near-term planned posts.
-   Show reminders for lead follow-ups due soon or overdue.
-   Export planned posts as a calendar file, optionally limited to one
    client, so schedules can be imported into a calendar application.

Ollama needs a running local service, compatible models, and sufficient
computer resources. Cloud AI API usage may have a cost. Keep manual and
rule-based drafting available when AI is unavailable.

### Phase 3 --- Meta integration

-   Create and configure a Meta developer app.
-   Implement the required authorization flow.
-   Keep each client's authorized Page and linked professional Instagram
    account separate; encrypt stored tokens and support revocation.
-   Make generated image media available in a secure, compatible public
    location before Instagram image publishing.
-   Connect eligible client-owned Facebook Pages, Instagram professional
    accounts, and advertising accounts after client authorization.
-   Reuse each client's authorized platform connection across their
    content, lead, and reporting workflows.
-   Implement permitted publishing and insights features.
-   Refresh available current engagement totals for posts published through
    MarketingPilot; expand to reach and historical insights only after adding
    the required Meta permissions and validating their API support.
-   Connect Meta lead forms to the client inbox.
-   Where supported, use Meta's phone SMS verification; otherwise verify
    synced leads through a configured SMS/email provider. Verify mailbox
    ownership with an email link or code rather than treating a work-email
    format check as proof. Require consent, secure hosted endpoints, and
    provider credentials before sending verification messages.
-   Handle expired tokens, permission errors, retries, and logging.
-   Keep a human approval step before publication.

Publishing access depends on the relevant account type, permissions, app
configuration, and platform policies. Until integration is fully
configured and tested, use Meta Business Suite for scheduling.

### Phase 4 --- Google Ads reporting

-   Start with manual exports or CSV imports.
-   Connect the client's Google Ads account only after authorization.
-   Add Google Ads API access after reviewing the developer
    requirements.
-   Retrieve permitted campaign performance data.
-   Import lead-form submissions through supported CSV, webhook, or API
    options as access permits.
-   Produce clear reports and recommendations.
-   Add campaign changes only later, with appropriate safeguards and
    client authorization.

Google Ads API access and production use may require approvals or other
setup. Advertising spend is paid by the client directly to the
advertising platform and is separate from our service fee.

### Phase 5 --- Reliable multi-client product

-   Add stronger authentication and authorization.
-   Separate each client's data.
-   Improve error monitoring, backups, and audit logs.
-   Add secure deployment and hosting.
-   Test reliability and document onboarding.
-   Consider subscriptions only after validating demand with real
    customers.

## 6. Can MarketingPilot run on a desktop without a domain?

**Yes.** During development, the app can run locally on your own
computer. For example, a local web server may be available at:

`http://127.0.0.1:8000`

or

`http://localhost:8000`

You do not need to buy a domain, pay for hosting, or make the app public
to use it on that computer. The computer must be switched on, and the
app's server process must be running.

### What local hosting means

-   The app is accessible through a browser on the same computer.
-   Data can be stored in a local database file.
-   It is suitable for development, testing, and early demonstrations.
-   If the server stops, the local web app will no longer be available
    until restarted.
-   A local app is not automatically accessible to clients over the
    internet.
-   External platform APIs still require internet access and the
    relevant credentials and permissions.

### What if clients need to access it remotely?

Later, we can deploy it to a hosting provider and configure a domain if
needed. Some providers offer limited free tiers, but availability and
limits can change. A public deployment also requires careful security,
authentication, HTTPS, backups, and protection of client data.

Do not expose a development server directly to the public internet or
place API secrets in client-side code.

## 7. Suggested development stack

The initial prototype can use:

-   **Python** for application logic
-   **FastAPI** for local web routes
-   **SQLite** for local data storage
-   **HTML/CSS** for the interface
-   **Git** for version control
-   **Official Meta and Google APIs** for later integrations, subject to
    access and permissions

These choices are a starting point, not a permanent constraint. We
should inspect and test the current code before making architectural
changes.

## 8. Business strategy

The practical order is:

1.  Build a sample campaign for one niche.
2.  Talk to prospective customers and understand their needs.
3.  Offer a small, clearly scoped service.
4.  Deliver work with free tools and human review.
5.  Record what takes the most time and what clients value.
6.  Automate those repeated tasks in MarketingPilot.
7.  Expand the service and product based on evidence.

A possible initial service could include a monthly content calendar,
captions, creative briefs, scheduling support, and a simple performance
report. Prices should be tested with actual prospects rather than
assumed in advance.

## 9. First milestone checklist

-   [ ] Download and extract the current project.
-   [ ] Run the Windows startup script.
-   [ ] Open the local dashboard in a browser.
-   [ ] Test client creation and content creation.
-   [ ] Test saving and reloading data.
-   [ ] Identify and fix any errors.
-   [ ] Create a sample campaign for one business niche.
-   [ ] Generate a basic report.
-   [ ] Start contacting potential clients.
-   [ ] Only then choose the next automation feature based on what is
    useful.

## 10. What success looks like

### First milestone

A stable local app that can organize a sample client's marketing work.

### Early business milestone

A real business owner has reviewed the demo and agreed to test or pay
for a clearly defined service.

### Product milestone

A repeatable content workflow saves time and can be reused for more than
one client.

### Long-term vision

A dependable, secure marketing workspace that helps small businesses
manage content and understand campaign performance across social
platforms and Google Ads---with transparent automation and human control
over important decisions.

------------------------------------------------------------------------

**Guiding principle:** Build something useful, test it with real people,
and automate what has proven valuable. A working local prototype is
enough to start; a domain and paid hosting are not required for the
first phase.
