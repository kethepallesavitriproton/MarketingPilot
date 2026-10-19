# Meta publishing setup checklist

This checklist prepares the first official publishing connector. Connections
must be authorized separately for each client so their Pages and tokens are
never shared across client records.

## What the client needs

- A Facebook Page the client owns or is authorized to manage.
- For Instagram publishing, an Instagram Business or Creator account linked to
  that client's Facebook Page. Personal Instagram accounts are not supported
  by the Instagram API flow documented here.
- A person with the appropriate Page tasks to complete the Meta authorization
  flow and grant the requested access.

## What the MarketingPilot app needs

- A Meta developer account and a developer app configured for the relevant
  Facebook and Instagram APIs.
- The app ID and app secret configured in a private local `.env` file. Do not
  put either value in source code, browser JavaScript, or a message to the
  developer.
- A redirect URL that matches the app's Meta configuration. Localhost may be
  suitable for development authorization; a hosted customer service needs its
  own HTTPS callback and security review before launch.
- The narrow permissions needed for each feature. Page discovery and Page
  publishing use Page access and publishing permissions. Instagram publishing
  requires its publishing permission and an eligible linked professional
  account. Meta can require additional access review before an app can serve
  accounts outside its development roles.
- A secure token-encryption key and a way to rotate or revoke client
  connections. Never store long-lived access tokens as plain text.

## Image publishing requirement

Instagram's publishing flow needs a compatible image at a public HTTPS URL so
Meta can fetch it. MarketingPilot prepares a JPEG and serves it from its public
HTTPS app address. This works for development while the HTTPS tunnel and app
are running; production use needs reliable public hosting. Facebook Page
publishing uses its separate direct upload flow.

## Local setup for the current connection flow

1. Copy `.env.example` to `.env` in the project folder and enter the app ID
   and app secret from Meta's developer dashboard.
2. The current local address (`http://127.0.0.1:8000`) is not secure enough
   for Meta authorization. Set `APP_BASE_URL` to a reachable HTTPS address
   with a valid certificate. If temporarily using a tunnel to the local app,
   first set a strong `APP_PASSWORD` and generate `APP_SESSION_SECRET`; do not
   expose the prototype without the password gate. This single password is
   only a development safeguard, not production multi-user authentication.
3. Leave `META_REDIRECT_URI` blank so MarketingPilot builds the callback from
   `APP_BASE_URL`, then copy the exact HTTPS callback shown on **Connections**
   into the Meta app's Facebook Login OAuth redirect settings.
4. Keep `META_GRAPH_API_VERSION` at the configured supported version unless
   Meta's app configuration requires a different version.
5. Generate a Fernet key using the command shown in `.env.example` and put the
   result in `META_TOKEN_ENCRYPTION_KEY`. Keep this key private and backed up;
   the app cannot decrypt saved Page tokens without it.
6. Restart `run_windows.bat` once so it installs the new dependencies and reads
   `.env`. Open **Connections**, then connect a client and select that client's
   Facebook Page.

Facebook authorization requests `pages_show_list`, `pages_read_engagement`, and
`pages_manage_posts`. Instagram requests additionally include
`business_management`, `instagram_basic`, and `instagram_content_publish` when
`META_INSTAGRAM_ENABLED=1`. The Meta app
must have the Instagram API with Facebook Login use case configured before you
turn that setting on. Meta may require app review before these permissions can
be used for client accounts outside development roles.

## Enable Instagram publishing

1. In the Meta developer app, add the Instagram API with Facebook Login use
   case/product and make sure the app can request `instagram_basic` and
   `instagram_content_publish`.
2. Set `META_INSTAGRAM_ENABLED=1` in the private `.env` file and restart
   MarketingPilot.
3. On **Connections**, reconnect the client's Page. Its Facebook Page must be
   linked to an Instagram Business or Creator account. The linked account will
   appear in the connection list when Meta returns it.
4. Create an Instagram content item with a generated image, mark it **Approved**,
   and use the explicit **Publish to Instagram** action. Keep the HTTPS tunnel
   and app running while Meta fetches the image.

The Instagram API supports professional Business or Creator accounts linked to
a Page in this Facebook Login flow. Its image publishing path uses a public
image URL and a media container before the final publish call. See [Meta's
Instagram API collection](https://www.postman.com/meta/instagram/documentation/6yqw8pt/instagram-api).

## Implementation status and next steps

1. Configure the Meta developer app and local callback URL as above.
2. Per-client OAuth authorization and Page selection are implemented. Tokens
   are encrypted with the local Fernet key.
3. Facebook Page publishing is implemented as an explicit action for approved
   content. It supports text posts and posts with a generated image; generated
   artwork is converted to PNG and uploaded directly to Meta. The returned post
   ID, link, and time are recorded. A rejected request can be retried after
   review; an uncertain network result is locked until the Page is checked to
   avoid duplicate posts.
4. Single-image Instagram feed publishing is implemented for approved content.
   It requires an eligible linked Business or Creator account, Instagram
   permissions, and public HTTPS access to the generated JPEG. Stories, Reels,
   carousels, and paid ads are not included.
5. The content planner can manually refresh current organic engagement totals
   for MarketingPilot-published Facebook and Instagram posts. Facebook shows
   reactions, comments, and shares; Instagram shows likes and comments. This
   does not retrieve reach, clicks, leads, or spend, and is not historical
   reporting. Refresh requires the post to remain available and the connected
   account to retain access.
6. The user has confirmed successful Facebook and Instagram image publishing
   with the configured developer account. Complete any Meta review required
   before connecting customer accounts.

Connecting a Page does not publish anything. Publishing requires an explicit
action on approved Facebook or Instagram content. No paid ad campaign is
created or launched by this feature.

## Current local project status

- The Meta developer app lists the developer account as an administrator.
- The local HTTP callback is rejected by Meta's secure-login check. MarketingPilot
  now requires a reachable HTTPS callback and a configured workspace password
  before enabling Meta authorization.
- MarketingPilot has a Connections page and a per-client OAuth authorization
  flow with a one-time state check, Facebook Page selection, and encrypted
  Page-token storage.
- Direct publishing supports approved Facebook Page posts with text and optional
  generated image, after the app has a reachable HTTPS callback, workspace
  password protection, and that client's connected Page. Text and image
  publishing have been confirmed on a developer Page.
- Instagram single-image feed publishing and Facebook Page image publishing
  have both been confirmed by the user. WhatsApp Status, Google Ads, and paid-ad
  campaign creation or launch are not implemented.
- Engagement refresh is available from the content planner for published
  Facebook and Instagram posts. Historical insights and reach/click reporting
  still need additional Meta permissions and implementation.

## References

- [Meta's official Instagram API collection](https://www.postman.com/meta/instagram/documentation/6yqw8pt/instagram-api)
- [Meta's official Page access-token collection](https://www.postman.com/meta/facebook/request/bqfxwbp/get-access-tokens-of-pages-you-manage)
- [Meta's official developer resources](https://developers.meta.com/resources/)
