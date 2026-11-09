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
project. A personal API key, GitHub integration and session replay are unnecessary.
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

README referral measurement uses an allowlist, not automatic URL or referrer capture.
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
| `$pageview` | A pathname navigation in the catalog; only its page category is sent. Count distinct browser IDs for weekly visitors. A filter change is not a new pageview. |
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
remains linked to a catalog entry. Read the directory at `/api/v1/developers/`
and profiles at `/api/v1/developers/{github_id}`.

The Developers directory accepts `q` (GitHub username), `repository` (exact
owner/name), and the catalog's `topic`, `target`, and `contribution` slugs.
A repo must link to one work matching all selected facets. Cards count matching
repos and feature one of them. Sort by `repos` (default) or `stars` (sum across
distinct matching owned repos with known star counts). Request
`include_facet_counts=true` to see distinct developer counts after replacing
each individual filter while retaining the others, including username and repo.
The MCP tools `list_developers` and `get_developer` use the same endpoints.

### Public HTML and Markdown

With `PWC_DISCOVERY_CATALOG=true`, FastAPI serves visible initial HTML at `/`,
`/catalog` and `/paper/{reference}`. React replaces that initial document when it
loads. The catalog uses the same filters and 25-row offsets as the API, with
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
