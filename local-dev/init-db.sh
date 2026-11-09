#!/bin/sh
# Bootstrap ONLY the isolated, empty local catalog. Never a general migration runner.
set -eu
PWC_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$PWC_ROOT"
sh local-dev/compose.sh up -d --wait db
COUNT=$(sh local-dev/compose.sh exec -T db psql -U pwc_local -d pwc_local -Atc \
  "SELECT CASE WHEN to_regclass('public.papers') IS NULL THEN 'missing' ELSE 'exists' END")
if [ "$COUNT" = exists ]; then
  COUNT=$(sh local-dev/compose.sh exec -T db psql -U pwc_local -d pwc_local -Atc 'SELECT count(*) FROM papers')
  if [ "$COUNT" != 0 ]; then
    echo 'Refusing bootstrap: local catalog already contains papers. Use reviewed migrations.' >&2
    exit 1
  fi
fi
sh local-dev/compose.sh exec -T db psql -U pwc_local -d pwc_local -v ON_ERROR_STOP=1 \
  -c 'CREATE EXTENSION IF NOT EXISTS vector; CREATE EXTENSION IF NOT EXISTS pg_trgm;'
sh local-dev/compose.sh run --rm --no-deps backend python -m backend.database.connection init
# create_all does not install upstream's SQL-managed views, search triggers,
# redirects or embedding tables. Apply the existing upstream files unchanged.
for migration in \
  add_paper_search_vector.sql \
  add_paper_search_vector_index.sql \
  add_entity_search_vectors.sql \
  add_entity_search_indexes.sql \
  add_paper_embeddings.sql \
  add_discovery_catalog.sql \
  add_discovery_developers.sql \
  add_paper_redirects.sql \
  update_trending_view_for_ema.sql
do
  echo "Applying upstream migration: $migration"
  sh local-dev/compose.sh exec -T db psql -U pwc_local -d pwc_local -v ON_ERROR_STOP=1 \
    < "backend/database/migrations/$migration"
done
