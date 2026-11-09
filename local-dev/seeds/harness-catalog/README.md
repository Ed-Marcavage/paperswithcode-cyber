# Security harness papers, engineering posts and organizations

This incremental seed adds 14 reviewed papers, 11 industry posts and two standalone repositories to the 136-entry cyber catalog. The 14 organization profiles link to sources for each attribution in `organizations.json`. The case studies use publisher links and original catalog descriptions. Each included paper document contains its source, author attribution, license and conversion notice. Paper asset provenance is recorded in `provenance.json`.

On a running local catalog, prepare the publisher preview images and copy the seed into a new working directory. Use a fresh output path when regenerating images.

```sh
local-dev/compose.sh exec backend python -m local-dev.catalog_post_previews /app/local-dev/seeds/harness-catalog /tmp/harness-review
local-dev/compose.sh exec backend python -m local-dev.import_catalog /tmp/harness-review/catalog.json --append
local-dev/compose.sh exec backend python -m local-dev.import_catalog /tmp/harness-review/catalog.json --append --execute
local-dev/compose.sh exec backend python -m local-dev.repository_catalog /tmp/harness-review/repositories.json --fetch-current --execute
local-dev/compose.sh exec backend python -m local-dev.import_catalog_organizations /tmp/harness-review/organizations.json --execute
```

The research affiliations and the two links to existing Shellphish and OpenSSF records require the existing base catalog. Repository ownership supplies the distinct star totals; publisher and paper affiliation links supply the work lists. The catalog refresh job updates the upstream organization Trending snapshots after its GitHub star pass. The activity calendar counts dated paper and post publications. OpenAI's Defense Factory has a year only.
