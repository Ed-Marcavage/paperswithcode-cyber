# Cyberintel discovery catalog

Run the catalog on a single machine with Docker Compose and Python 3.9+. The UI,
API and read-only MCP share one origin. Only the frontend is published, on
loopback. Chat, agent/edit jobs, paid document extraction and scheduled imports
are off. Keyword search and reading the cache do not require a model key.

## Start the review environment

From the repository root, using a Docker context that can build Linux images:

    python3 local-dev/configure.py
    sh local-dev/compose.sh build
    sh local-dev/init-db.sh
    sh local-dev/compose.sh up -d --wait

Open [Trending](http://localhost:8095), [Browse catalog](http://localhost:8095/catalog),
[API documentation](http://localhost:8095/docs/api), or [MCP setup](http://localhost:8095/mcp).
Use `configure.py --port PORT` when creating a new environment to change the
port. The script creates a private, ignored `.local.env` once; retain it for
the lifetime of the database. `sh local-dev/compose.sh stop` keeps the volume.
No VPN, cloud credentials or domain is needed. This Vite profile is for local
review; it is not a public web server deployment.

## From legacy data to the UI

The v2 SQLite knowledge database has a `work` table with bibliographic fields
and a `fulltext_path` pointing to the corpus text. For EVMbench it contains
the arXiv ID, date, abstract, and a cached document path. It does not define the catalog's reviewed UI taxonomy. The hand-off
between curation and loading is a version 1 catalog JSON: `names` contains the
vocabulary for topic, target, contribution, kind and year, and each item in
`rows` has a stable ID, title, source URL, available bibliographic fields, and
arrays of vocabulary slugs in `facets`. Missing evidence stays missing. Keep
raw exports, document indexes, bundles and dumps outside Git.

1. Prepare the reviewed export and any document index. The index is keyed by
   catalog ID; each selected `files.text` points to UTF-8 text under an
   explicitly allowed input directory. To show paper thumbnails, include
   `files.pdf` for records with a known local PDF. Supply precise project URLs separately
   from repository-root URLs, using an artifact map such as
   `{"arxiv:2603.04915":"https://github.com/openai/frontier-evals/tree/main/project/evmbench"}`.
   For an external conference paper, the row may also supply
   `conference_url_pdf`: the verified PDF on the publisher's site. Keep
   `url` as the canonical paper page. For arXiv papers, pin the reviewed
   revision in the source URL and set `arxiv_id` and `version`.
2. Build the portable bundle. This command illustrates the 75-paper review:
   it carries over indexed extracts and also selects the legacy EVMbench
   document by catalog or arXiv ID. The v2 database is opened read-only. Relative
   text paths resolve against the supplied v2 corpus root. Omit optional
   arguments for sources you do not have.

       python3 local-dev/prepare_catalog.py reviewed/catalog.json data/bundle \
         --documents reviewed/documents.json --text-root reviewed \
         --artifacts reviewed/artifacts.json \
         --v2-db corpus/data/knowledge/knowledge.db --v2-root corpus --text-root corpus/data/text \
         --v2-text-for arxiv:2603.04915

   To render first-page thumbnails, install Poppler and pass `--pdf-root` for
   each allowed PDF directory. The packager uses `pdftoppm` on indexed PDFs
   and stores only small JPEGs in the bundle. The importer saves those images
   with their paper records, so database backups include them. A bundle built
   without PDF roots preserves existing thumbnails. A preview-enabled bundle
   clears a managed thumbnail if the record no longer has an indexed PDF.

   Only reviewed IDs are packaged; text is copied under portable relative paths.
   The packager checks declared text checksums, caps each document at 4 MiB
   and will not overwrite an existing bundle. No source PDFs are distributed.
3. The importer checks the entire catalog. To add a batch, retain the previous
   release's rows and assets and append the reviewed additions. Include cached
   text only where it can be served; a row without a text file falls back to
   the paper's source link. Copy the complete bundle into the backend, then
   preview and apply the same file:

       sh local-dev/compose.sh cp data/bundle backend:/tmp/reviewed
       sh local-dev/compose.sh exec -T backend python local-dev/import_catalog.py /tmp/reviewed/catalog.json
       sh local-dev/compose.sh exec -T backend python local-dev/import_catalog.py /tmp/reviewed/catalog.json --execute

   Preview rolls back schema and data together. The import reuses native papers
   (versioned arXiv ID or canonical external URL) and author/topic links. Catalog
   ID maps to native paper ID, not to an array position. Reviewed facets, the
   exact artifact and cached text live in `discovery_works`; display names live
   in `discovery_terms`. Native metadata is not overwritten on reimport. A
   repeat preview must report zero new papers and zero added or removed topic links.
4. Import official associations and star observations separately. Copy your
   reviewed repository manifest into the backend and run
   `python local-dev/repository_catalog.py /tmp/repositories.json` there; add
   `--execute` after preview. Each link requires a source and an evidence note.
   Snapshots need a precise timestamp within 24 hours; use `--fetch-current`
   to obtain new public observations for a stale manifest. The optional
   `catalog-refresh` Compose profile refreshes repository observations only.

For the existing 75 records, the acceptance command is:

    python3 local-dev/check_catalog.py

It initializes a real Streamable HTTP client, lists read-only tools, searches,
combines facets, checks the official repository and specific artifact, walks
every signed EVMbench text cursor and compares the result with the browser's
document bytes. It also checks missing text and write rejection. To check the
UI by hand, use Browse catalog → Target: Smart contracts → Contribution:
Benchmark → EVMbench. Try the search overlay with Enter and open the MCP setup
page. A paper marked “Benchmark” can have no structured leaderboard results.

## How MCP works

The frontend and MCP read the same FastAPI service. `GET /mcp` in a browser
opens setup instructions; MCP clients send JSON-RPC to the same URL.
`catalog_filters` and `browse_catalog` call `/api/v1/catalog/filters` and
`/api/v1/catalog/papers`. `get_paper_info` adds curated metadata to the
native paper response. `read_paper` uses the versioned
`/api/v1/research/papers/{id}/read` endpoint. Postgres holds the text; no
runtime OCR or model dispatch is involved. When no text is cached, the
reader returns a source link. The project artifact may be a subdirectory;
Trending credits stars to the enclosing GitHub repository. MCP adds no
server-side chat agent; a client can use its own assistant.

The MCP image builds a pinned revision of [the CLI fork](https://github.com/Ed-Marcavage/pwc-cli-cyber) with
the catalog changes in `mcp.patch`. A standalone CLI also needs
`PWC_API_URL=http://localhost:8095/api/v1` to search this local catalog.
API responses, schema discovery and
client setup point at the review origin.

## Rebuild, restore and promotion

With `VITE_LOCAL_CATALOG=true`, Vite prepares the three Personal agents icons
when starting the dev server or building the static site. It fetches each
provider's artwork once, verifies its SHA-256, and caches it in the Git-ignored
`frontend/.personal-agent-icons/`. Visitors receive the icons in the site's
own frontend bundle. For an offline build, copy the verified `dots.svg`,
`grok-bot.jpg`, and `muse.svg` into that directory before starting Vite or
building the Compose frontend image. A populated cache works without network
access. The pinned URLs and digests are in
[`personalAgentArtwork.ts`](../frontend/personalAgentArtwork.ts).

- For code changes: rebuild the affected service (`sh local-dev/compose.sh
  build frontend`, for example), then `sh local-dev/compose.sh up -d --wait`.
  Run the acceptance command and UI checks before promoting a commit.
- For a restored catalog: start only `db` in a fresh Compose project, restore
  a PostgreSQL 16 custom dump into the empty database with
  `sh local-dev/compose.sh exec -T db pg_restore -U pwc_local -d pwc_local
  --exit-on-error --no-owner --no-acl < catalog.dump`. Skip `init-db.sh` for
  this path. Start the services and apply the reviewed discovery bundle.
- Before a hosted rollout, record the reviewed Git commit, the bundle checksum,
  the repository manifest, and a verified database backup. Promote that build
  behind the deployment's HTTPS proxy with its own origin/host allowlist.
  Test MCP initialization and continuation through the proxy as well as the
  browser. Roll back the application and a compatible database snapshot
  together if checks fail. A local review never deploys automatically.

### Optional catalog analytics

PostHog is off unless you set its public project token. Use the token that starts
with `phc_` and the ingest host shown by the **manual React** setup for your
project. A personal API key and GitHub integration are unnecessary.
Set `VITE_POSTHOG_PROJECT_TOKEN` and `VITE_POSTHOG_HOST` in the ignored
`.local.env`; Compose passes only those analytics settings to the frontend and
MCP. Local events are labeled `preview`.

For a static release, build with the same public values and a new output directory:

```sh
cd frontend && npm ci && cd ..
python3 local-dev/build_catalog_site.py --environment production \
  --site https://your-domain.example --output /tmp/catalog-site-release
```

Build on a case-sensitive filesystem. The command turns off auth, chat, and agent
features and sets the social metadata to the selected site. Vite embeds public
configuration at build time. Changing the server environment alone will not
enable tracking in an existing static site. To disable tracking, rebuild with
an empty token and restart MCP without its analytics token. Never deploy the
workstation's complete environment file.

For the deployed MCP container, set `PWC_POSTHOG_PROJECT_TOKEN`,
`PWC_POSTHOG_HOST`, and `CATALOG_ANALYTICS_ENV=production` in server-local
configuration. The project token is the same public ingestion token. Enable **Privacy → Discard client IP data** in PostHog to prevent IP storage on future events. Configure
the browser's CSP to permit connections to the selected ingest host if the
site has a restrictive `connect-src`. Browser or network blocking can reduce
these counts. Analytics outages and rate spikes do not block MCP requests.

#### Session replay

The catalog build records sessions when the PostHog project has replay switched
on; with replay off in the project, nothing is recorded. The recorder is bundled
from `posthog-js/dist/posthog-recorder` as a same-origin chunk
(`startCatalogRecording` in `frontend/src/lib/catalogAnalytics.ts`), so external
script loading stays off and no third-party script host is needed. Its
console-log and network plugins are removed after loading, so project settings
cannot turn on console or network capture. Settings live in
`catalogRecordingOptions` (`frontend/src/lib/posthogPrivacy.ts`):

- every input value is masked (the search box shows asterisks); text that echoes
  a typed search carries the `ph-mask` class and is masked too;
- page text is recorded unmasked, since it is public catalog content; account UI
  cannot render in the catalog build (auth is off) and is blocked if it ever does;
- recorded page addresses keep only origin and path (no query string or fragment);
- no canvas, cross-origin iframes, request headers or bodies, console logs,
  autocapture, heatmaps, surveys or feature-flag requests.

Replay needs the project's remote config, so the catalog sets
`advanced_disable_flags: false` and fetches it as JSON from the PostHog assets
host (`https://us-assets.i.posthog.com/array/<token>/config` for the US region);
`advanced_disable_feature_flags` keeps `/flags` requests off. `before_send` lets
`$snapshot` batches through with the recorder's own fields only. Do Not Track or
Global Privacy Control still means no `posthog.init`, so no analytics and no
recording. The privacy page states a 30-day recording retention; keep the
project's replay retention at 30 days or update the page.

PostHog project settings this code depends on (set at release, not in code):
**Session replay → Record user sessions** on (the switch); **retention 30 days**;
**Authorized domains for replay**, if used, must list the production domain;
leave **Capture console logs**, **Capture network requests**/payloads and
**Canvas capture** off (the client ignores console and network either way, and
forces canvas off); keep **Privacy → Discard client IP data** on. If the site
has a restrictive CSP, `connect-src` must allow the ingest host and the assets
host; no `script-src` change is needed because the recorder is served from the
site itself. The local-dev nginx fragment sets no CSP.

#### Referrals

The landing `$pageview` (the first in a page load) carries `referral_domain`:
the referring site's host without `www.` (for example `news.ycombinator.com`),
never its path or query, and nothing when the referrer is the catalog itself or
is not an http(s) URL. SDK referrer properties are still dropped.

README referral measurement uses an allowlist, not automatic URL capture.
Links with `utm_source=github`, `utm_medium=readme`, and
`utm_campaign=awesome-security-agent-harnesses` add fixed `referral_source` and
`referral_campaign` properties to the landing `$pageview`. `utm_content=catalog`
or `utm_content=mcp` adds `referral_link`; all other campaign values are dropped.
The label is not persisted to later visits. In PostHog, filter production
`$pageview` events by `referral_campaign` and count unique visitors. Compare that
with GitHub repository visitors for the same dates as an estimated referral rate;
GitHub does not expose README impressions or outbound clicks, and browser privacy
controls can reduce the measured visits.

| Event | Meaning |
| --- | --- |
| `$pageview` | A pathname navigation in the catalog; only its page category is sent, plus `referral_domain` on the landing pageview when another site linked here. Count distinct browser IDs for weekly visitors. A filter change is not a new pageview. |
| `$snapshot` | Session replay data (masked as described above), only when the project has replay switched on. Linked to the other events by `$session_id`. |
| `catalog_navigation` | A person clicked Browse catalog or MCP in the desktop or mobile top navigation. A direct visit still counts as a pageview. |
| `taxonomy_selected` | Someone chose a labeled Top Domain, a catalog filter value, or a taxonomy link on a paper. Includes the surface, axis and value. |
| `paper_link_clicked` | A visitor activated a public paper title or thumbnail. Includes the displayed paper title, ID, source surface and link part; captures keyboard, new-tab and middle-click activation, never hover or prefetch. |
| `paper_opened` | The paper detail loaded successfully; includes its public catalog ID, title and facets. A thumbnail request or hover does not count. |
| `paper_resource_clicked` | Intent to open a resource. Direct PDF links count as `pdf`; the reader, cached text, publisher landing pages and other artifacts have separate values. Recognized repository links count as `code`. It does not prove a download completed. |
| `catalog_mcp_tool_called` | A named JSON-RPC `tools/call` request for a registered tool. Counts attempts, including errors and retries, by tool and HTTP status. A 200 is not proof of tool success. The single service ID is not a visitor; handshake, list, health and web page visits do not count. |

For a weekly review, filter to `catalog_environment=production`. Compare weekly
unique pageview visitors with unique paper readers and PDF/code clickers. Over
the last four weeks, rank papers by distinct readers who used a resource on the
detail page, and compare those counts with distinct detail opens. Break paper
opens down by topic, target and contribution; cross-check against deliberate
domain/filter choices. Papers can have multiple tags. A visible link's popularity
also reflects its placement. Review MCP calls by tool separately. Small counts
are a prompt to inspect a few papers, not a reason to expand a category.

### Developers

The Developers directory groups GitHub user accounts by their work on tracked
repositories. Accounts and repos use numeric GitHub IDs. Ownership and positive
GitHub contributor counts are separate relationships. GitHub can attribute
commits to an account shared by a team or automation. A contributor total
does not identify a paper author or supply daily activity.

The optional `local-dev/seeds/developer-repos/` batch contains the 27 reviewed
user-owned repositories from the Awesome list. Cybench and ChatAFL link to
existing papers. The 25 other repos have standalone entries. Import this seed
into the existing local Cyber Edition catalog with:

```sh
sh local-dev/compose.sh exec -T backend python -m local-dev.import_catalog /app/local-dev/seeds/developer-repos/catalog.json --append --execute
sh local-dev/compose.sh exec -T backend python -m local-dev.repository_catalog /app/local-dev/seeds/developer-repos/repositories.json --fetch-current --execute
```

To populate or refresh profiles, run the collector on the host with an authenticated
GitHub CLI. It follows all contributor pages and saves public user IDs, logins,
ownership and contribution counts. Use a fresh output path for each run. Failed
repo reads are reported and excluded from the snapshot, preserving the previous
observation for those repos. GitHub's contributors endpoint can omit identities
it cannot resolve to an account.

```sh
python3 local-dev/fetch_developers.py /tmp/developers.json
sh local-dev/compose.sh cp /tmp/developers.json backend:/tmp/developers.json
sh local-dev/compose.sh exec -T backend python /app/local-dev/import_developers.py /tmp/developers.json
sh local-dev/compose.sh exec -T backend python /app/local-dev/import_developers.py /tmp/developers.json --execute
```

The import applies the Developers migration to an existing local catalog. A
replay skips snapshots already applied. Profiles list work only while its repo
remains linked to a catalog entry by a credited (`is_official`) link. The
collector reads only credited repositories, and the same snapshot carries each
repo's star observation, which the import stores like `repository_catalog.py`.

### Industry-post links

`import_post_links.py` links every industry post to its publisher organization
and to every repository its review cites. The publisher comes from the post's
host through the reviewable file `backend/config/publisher_organizations.json`
(one flat organization per company; an existing record with the same name or a
website on a mapped host is reused). Repository links keep the review's role
(`original`, `target`, `supporting`, `dependency`), evidence sentence and cited
URL; one repository record per GitHub owner/name, compared case-insensitively.
Only roles in `CREDITED_ROLES` (default `original`) set `is_official`, which is
what the Developers tab and star-based Trending count. Run it after the review
fields are loaded, then the developer collector above:

```sh
sh local-dev/compose.sh cp bundle/v2-fields.json backend:/tmp/v2-fields.json
sh local-dev/compose.sh exec -T backend python local-dev/import_post_links.py /tmp/v2-fields.json
sh local-dev/compose.sh exec -T backend python local-dev/import_post_links.py /tmp/v2-fields.json --execute
```

`/api/v1/catalog/repositories/{owner}/{name}` lists the papers and posts citing
a repository, grouped by role; the site shows it at `/repos/{owner}/{name}`,
linked from a post's GitHub card, repository entries and developer profiles.

Publisher organizations the mapping creates start bare. Their GitHub
organization and avatar logo come from the reviewed profile manifest
`seeds/publisher-organizations/organizations.json` (42 of 47; each login was
checked against the GitHub profile's name and website), applied like the
other organization seeds:

```sh
sh local-dev/compose.sh cp local-dev/seeds/publisher-organizations/organizations.json backend:/tmp/publisher-organizations.json
sh local-dev/compose.sh exec -T backend python local-dev/import_catalog_organizations.py /tmp/publisher-organizations.json --execute
``` Read the directory at `/api/v1/developers/`
and profiles at `/api/v1/developers/{github_id}`.

The Developers directory accepts `q` (GitHub username), `repository` (exact
owner/name), and the catalog's `topic`, `target`, and `contribution` slugs.
A repo must link to one work matching all selected facets. Cards count matching
repos and feature one of them. Sort by `repos` (default) or `stars` (sum across
distinct matching owned repos with known star counts). Request
`include_facet_counts=true` to see distinct developer counts after replacing
each individual filter while retaining the others, including username and repo.
The MCP tools `list_developers` and `get_developer` use the same endpoints.

### Post preview images

A post's card preview is a screenshot of its page: the top 1280x1760 pixels at
a 1280x900 viewport, scaled to 400x550, JPEG quality 85. If the screenshot is
rejected, the publisher's social image is used; if there is none, a title card.
`post_screenshot.mjs` takes the screenshot, one page at a time, with a desktop
Chrome user agent, a settle wait of about 5 s, one retry after a load failure,
HTTP 429 or 5xx, and consent banners and dimming layers removed. A capture is
rejected for HTTP 400 or above, a challenge or block page (a `cf-mitigated`
header, a challenge-page element, challenge wording in the title, or a captcha
widget or challenge wording in a page with under 3,000 characters of text), or a mostly blank image (92% or more of
pixels within 8 grey levels of the most common one). Challenges are not worked
around. Details are in `post_previews.py`.

Preview destinations must be public HTTP(S) URLs on ports 80 or 443. Initial
pages, redirects, frames and subresources are checked against every resolved
IPv4/IPv6 address; loopback, private, link-local, unique-local and other non-public
ranges are refused. The browser uses a local filtering proxy that connects to
checked IPs, preventing DNS rebinding between validation and connection. Request
interception is enabled, service workers and WebSockets are blocked, and direct
WebRTC/QUIC traffic is disabled. A refused destination rejects the screenshot
with a reason in the report. Publisher artwork uses the backend's pinned,
redirect-aware public fetcher for both the page and image; if that is refused,
the title card requires no network. Catalog-derived URLs follow the same path.
The explicitly configured catalog API is trusted operator input for ID lookup;
its returned source URL is still untrusted and checked before previewing.

Screenshots run on the host, not in the backend container. They need Node on
`PATH`, a Playwright package and an installed Chromium; nothing is downloaded:

```sh
export PWC_PLAYWRIGHT_CORE=~/.npm/_npx/<hash>/node_modules/playwright-core
export PWC_CHROMIUM=~/Library/Caches/ms-playwright/chromium-1217/chrome-mac-arm64/"Google Chrome for Testing.app"/Contents/MacOS/"Google Chrome for Testing"
```

Without `PWC_CHROMIUM`, Playwright's own expected build is used. The commands
stop with an explanation if Node, Playwright or Chromium is missing.
`--no-screenshots` keeps artwork or title card only.

New posts get previews from `catalog_post_previews.py` as before (see
`seeds/harness-catalog/README.md`); `previews/report.json` in the output
bundle records the method per post and why a screenshot was rejected. To
refresh posts already in the catalog, write the images to a new folder, check
the contact sheet, then load them as a separate step:

```sh
uv run python local-dev/refresh_post_previews.py shoot /tmp/post-previews 1008 https://example.com/post --api http://localhost:8095
uv run python local-dev/refresh_post_previews.py sheet /tmp/post-previews
sh local-dev/compose.sh cp /tmp/post-previews backend:/tmp/post-previews
sh local-dev/compose.sh exec -T backend python local-dev/load_post_previews.py /tmp/post-previews/manifest.json
sh local-dev/compose.sh exec -T backend python local-dev/load_post_previews.py /tmp/post-previews/manifest.json --execute
```

`shoot` takes paper ids (resolved through the catalog API) or post URLs, or
`--from-file` with one per line. `manifest.json` lists each post's file,
SHA-256 digest, method and rejection reason. The load is a dry run that only
reads the database unless `--execute` is given. It stores each JPEG in
`discovery_previews` under its digest and sets `papers.thumbnail_url` to
`/api/v1/catalog/papers/{id}/preview/{digest}.jpg`, as `import_catalog.py`
does. It skips posts whose URL differs from the manifest and posts whose
thumbnail came from elsewhere. The backend image must include this commit, or
copy `load_post_previews.py` into the container with the folder.

### Public HTML and Markdown

With `PWC_DISCOVERY_CATALOG=true`, FastAPI serves visible initial HTML at `/`,
`/catalog` and `/paper/{reference}`. React replaces that initial document when it
loads. JavaScript-enabled browsers show a brief loading state to avoid flashing
the alternate layout. The initial document stays visible without JavaScript and
is restored if the app bundle fails or takes more than four seconds to load.
Humans and crawlers receive the same HTML and loading behavior. The catalog uses
the same filters and 25-row offsets as the API, with
crawlable pagination links. Filtered selections are `noindex,follow`; each
unfiltered page has its own canonical. Unknown paths and missing papers return
404. Other recognized browser routes retain their SPA views and are not included
in the sitemap yet.

`/index.md`, `/catalog.md` and `/paper/{reference}.md` provide the same page data
as Markdown. `Accept: text/markdown` on the HTML URL also works; shared caches must
honor `Vary: Accept`. The canonical always identifies the HTML representation.
`/robots.txt`, `/sitemap.xml` and `/sitemaps/*.xml` are backend documents, not SPA
fallbacks. The sitemap includes only the homepage, unfiltered catalog pages and
reviewed catalog papers. `/llms.txt` describes the Markdown and MCP entry points.

For a separately authorized release, build a new immutable frontend directory
using `build_catalog_site.py --site https://paperswithcode-cyber.com` and mount
that **same directory** into the matching backend release. The optional
`compose.public-pages.yaml` overlay sets `PWC_FRONTEND_DIST_DIR`; set
`CYBER_FRONTEND_DIST` to the host build path. `PWC_PUBLIC_SITE_URL` is a validated
HTTPS origin and must match the build's `--site`. Canonicals never trust Host.

Adapt `nginx-public-pages.conf` inside the existing Cyber server block, replacing
the old `location /` SPA fallback and any overlapping paper/discovery locations.
Keep the existing API, MCP Accept/method negotiation, PDF reader and immutable
asset routing. The example targets the Cyber backend on port 8018. This is an
integration fragment, not a replacement server configuration. Validate the
assembled config in an isolated unprivileged nginx before any reload. Normal
Vite development still uses its own SPA fallback; test HTTP status and initial
HTML against FastAPI or the assembled proxy, not the Vite dev server.

Before publishing, check GET and HEAD for the discovery files, one existing and
one missing paper, an unknown path, HTML/Markdown negotiation, a paginated catalog,
assets, API, MCP browser/transport requests and the reader. Check JS-disabled
visibility and navigation after React loads. Set `PWC_ENVIRONMENT=staging` for
preview backends to emit crawl restrictions. Revert backend, frontend mount and
proxy fragment together if rolling back.

The Cyber homepage's Trending feed includes only records reviewed as `kind=paper`.
This filter runs before ranking and pagination for both API and initial HTML/
Markdown; repository-only records and existing posts remain in the full catalog.
Trending's posts feed (`GET /api/v1/catalog/trending-posts`, React's default
view) starts with the owner-pinned posts (`pinned` in `curated_posts.json`,
applied by `mark_curated_posts.py`) in pin order, each with an "Editor's pick"
badge, on the first page only; a date window keeps only the pinned posts
published inside it. The ranked featured, agent-related posts follow, without
the pinned ones. The initial HTML and Markdown list the same posts, pinned ones
labelled "Editor's pick", before the papers.
Future intake should poll engineering blogs (including OpenAI, Anthropic,
Cloudflare, Ramp and Shopify) hourly, detect new cyber-related posts, and feature
them on the day they are added. That scraper and daily placement are not implemented.

## Optional Cyber assistant (local review)

The independent catalog assistant uses Ollama cloud and the same read-only MCP
catalog. It does not enable upstream chat, OAuth, web search or editor jobs.
The backend and frontend switches default to false. Put the Ollama key only in
the private ignored `.local.env` as `PWC_ASSISTANT_API_KEY` (or supply it in the
process environment). Never put it in a `VITE_*` setting, command argument, log,
committed file or rendered Compose output. If `.local.env` is a symlink, retain
that link and manage its target privately. The implementer does not modify it.

For the reviewer to enable the assistant, set `PWC_ASSISTANT_ENABLED=true` and
`VITE_ASSISTANT_ENABLED=true` in that private configuration. Leave
`VITE_CHAT_ENABLED=false`. Compose passes the key to the backend only; no model
key is required by the frontend or MCP. Settings:

| Setting | Default |
| --- | --- |
| `PWC_ASSISTANT_BASE_URL` | `https://ollama.com/v1` |
| `PWC_ASSISTANT_MODEL` | `glm-5.3-flash` (provisional until evaluation) |
| `PWC_ASSISTANT_MCP_URL` | `http://mcp:7860/mcp` |
| `PWC_ASSISTANT_LIMIT_COOLDOWN_MINUTES` | `30` |
| `PWC_ASSISTANT_TURNS_PER_HOUR` | `30` (rolling hour) |
| `PWC_ASSISTANT_TURNS_PER_DAY` | `100` (rolling 24 hours) |
| `PWC_ASSISTANT_CONVERSATIONS_PER_HOUR` | `10` new chats (rolling hour) |
| `PWC_ASSISTANT_CONVERSATIONS_PER_DAY` | `30` new chats (rolling 24 hours) |
| `PWC_ASSISTANT_RETENTION_DAYS` | `90`, measured from last activity |

Compose permits the internal `mcp:7860` Host header and forces
`PWC_ASSISTANT_STORE_ANALYTICS_SESSION=false`; the browser never submits a
PostHog session id. No key produces a plain 503. A provider usage limit is stored
in the database and disables every composer until the reset; status checks do
not call a model. Temporary provider concurrency errors are retried briefly.

**Production must set `PWC_PUBLIC_SITE_URL` to the public HTTPS origin**, for
example `https://paperswithcode-cyber.com` (no path, query or fragment). This is
the authoritative origin for every unsafe assistant request, even when
TLS ends at nginx and the backend receives HTTP with an internal Host. An unset
value falls back to the request Host and HTTP(S) `X-Forwarded-Proto`, matching
the repository's existing nginx trust in `backend/routers/auth.py`; it does not
trust `X-Forwarded-Host`. Keep the backend behind the trusted proxy, and have the
proxy overwrite `Host` and `X-Forwarded-Proto` on every assistant API location.
Local direct HTTP development can leave the public origin unset; the Vite proxy
must preserve the browser's Host. POST, PATCH and DELETE are checked before a
visitor identity is issued. A mismatched Origin or `Sec-Fetch-Site: cross-site`
is refused. Without Origin, only `Sec-Fetch-Site: same-origin` is accepted;
non-browser clients must send a matching Origin. Bodies require
`Content-Type: application/json` (an optional charset is accepted).

Before enabling on an existing **local** database, the reviewer applies the
four additive migrations in order (a new empty database's `init-db.sh` uses
ORM `create_all`, which includes these tables):

```sh
for migration in add_assistant_history.sql add_assistant_runs.sql add_assistant_provider_limits.sql add_assistant_admission.sql
do
  sh local-dev/compose.sh exec -T db psql -U pwc_local -d pwc_local -v ON_ERROR_STOP=1 < "backend/database/migrations/$migration"
done
```

Then the reviewer rebuilds/restarts the backend and frontend using the normal
local workflow above. Implementation work does not start, stop or rebuild any
containers. Inspect the panel, `/chat`, reload restoration, a second browser
profile, and the three disabled composers using a fake provider. No host
`npm run build` is needed for implementation checks.

Read traces with the local backend environment (these commands need no model
key):

```sh
sh local-dev/compose.sh exec -T backend python -m backend.assistant_cli list --days 7
sh local-dev/compose.sh exec -T backend python -m backend.assistant_cli show RUN_ID
sh local-dev/compose.sh exec -T backend python -m backend.assistant_cli export --days 7 > /tmp/assistant-runs.jsonl
sh local-dev/compose.sh exec -T backend python -m backend.assistant_cli purge
```

Schedule the purge command daily in the review/deployment environment when
chat is enabled. It removes chats older than the configured last-activity
retention, including messages, tools, runs, steps and feedback. Sending,
completing, renaming and giving feedback update last activity; reading does not.
The disclosed default is 90 days; update the privacy page if changing it.

### Model evaluation

`backend.assistant_eval` asks the same 20 fixed questions in order, with fresh
history per question and the application's normal bounded loop. Its JSON Lines
output records question, named model, answer, status/error, tools and results,
links, duration, model-call count and input/output tokens (null when absent).
It writes each row immediately and stops on a provider usage limit. It neither
writes chat history to the database nor sends analytics. Like chat, it makes
bounded read-only post-metadata lookups with the backend database settings;
unavailable enrichment is marked in the tool result and does not fail the turn.

The specification author has authorized the **reviewer** to evaluate up to
three named models, 20 questions per model. The implementer must not run this
live evaluation; implementation tests use fake providers. Each model's run can
make up to 160 model requests within the existing per-question limits.

Inside the already-running backend container, the reviewer can use its existing
process environment (including the backend-only key) and internal MCP hostname:

```sh
python -m backend.assistant_eval \
  --model glm-5.3-flash --mcp-url http://mcp:7860/mcp \
  --output /tmp/assistant-evals/glm-5.3-flash.jsonl
```

From the host, the equivalent reviewer command is:

```sh
sh local-dev/compose.sh exec -T backend python -m backend.assistant_eval \
  --model glm-5.3-flash --mcp-url http://mcp:7860/mcp \
  --output /tmp/assistant-evals/glm-5.3-flash.jsonl
```

Retain the JSONL outside the container before it is replaced. To run directly on
the host instead, use the externally published local MCP endpoint:

```sh
uv run --env-file .local.env python -m backend.assistant_eval \
  --model glm-5.3-flash --mcp-url http://localhost:8095/mcp \
  --output .assistant-evals/glm-5.3-flash.jsonl
```

Outputs are ignored by Git and exclusive-created (use a new name for a repeat).
Review all 20 answers against their recorded tool evidence: supported facts,
real catalog links, no invented result for the deliberately missing title,
useful answers, failures, latency and token usage. Record the chosen model and
reason in the local implementation report; only then update the default if
needed. No evaluation results or model choice are claimed by the script itself.

### Nginx review configuration

Include `nginx-assistant-http.conf` once inside nginx's `http` block, then include
`nginx-public-pages.conf` inside the Cyber `server` block. The exact assistant
turn location permits **10 requests/minute per IP with a burst of 3**, returns a
plain, friendly 429 for excess traffic, disables proxy buffering and caching,
and allows 120 seconds for streaming. **Production must install this proxy
limit before enabling the assistant**: cookie limits alone cannot stop a caller
from discarding its cookie. Keep the backend inaccessible except through this
proxy and configure trusted real-client addressing if another proxy fronts it.
IP addresses are used only in nginx memory; none are stored in the database.

The backend atomically admits at most one turn per visitor and applies the
rolling quotas above to the hashed visitor cookie. Deleting chats does not
reset quotas. Completed, failed and disconnected streams release admission;
a 120-second stream timeout bounds provider work, and a five-minute lease
recovers admission after a crashed worker. Purge removes quota rows after a day
of inactivity. There are no global daily or concurrency caps; the existing
provider-allowance cooldown still switches the assistant off until reset.
Other assistant paths use the existing API proxy.
Production must set backend `PWC_PUBLIC_SITE_URL` to the public HTTPS origin.
Preserve the visitor's Host and overwrite `X-Forwarded-Proto` with `$scheme` in
that API proxy too, including conversation PATCH/DELETE and feedback POST paths.
The configured public origin takes precedence over those request headers.
The normal Vite review proxy streams directly; these fragments are for review,
not an instruction to deploy or reload nginx. Validate the assembled configuration
as an unprivileged isolated instance following `docs/development-guide.md`.
