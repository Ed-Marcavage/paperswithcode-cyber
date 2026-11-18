#!/usr/bin/env bash
# Reproduce the image's patch/frozen runtime install, then test without external services.
set -euo pipefail
: "${SCRATCH:?Set SCRATCH to a writable temporary directory}"
profile_dir=$(cd "$(dirname "$0")" && pwd)
clone=${1:-/Users/edmarcavage/Documents/me/2027/pwc-cli-cyber}
tree=$(mktemp -d "$SCRATCH/mcp-test.XXXXXX")
export UV_CACHE_DIR="$SCRATCH/uv-cache"
export PWC_SITE_URL=http://localhost:8140
export PWC_API_URL=http://127.0.0.1:1/api/v1
export PWC_MCP_CURSOR_KEY_CURRENT=test-only-cursor-secret
unset PWC_POSTHOG_PROJECT_TOKEN PWC_POSTHOG_HOST PWC_CATALOG_ONLY
# No checkout, fetch, or mutation in the base clone.
git -C "$clone" archive 125ffe07aad3d268bc2e3ddd8d79f159b4bc2f2b | tar -x -C "$tree"
patch -d "$tree" -p1 < "$profile_dir/mcp.patch"
cp "$profile_dir/mcp_profile.py" "$profile_dir/mcp_analytics.py" "$tree/mcp_server/src/pwc_mcp/"
uv sync --project "$tree/mcp_server" --frozen --no-dev --no-editable
# Test-only dependencies are already pinned in the same lockfile.
uv sync --project "$tree/mcp_server" --frozen --no-editable
python_bin="$tree/mcp_server/.venv/bin/python"
"$python_bin" -m pytest "$profile_dir/test_mcp_profile.py" "$profile_dir/test_mcp_analytics.py" -q --tb=short
status=0
(cd "$tree/mcp_server" && "$python_bin" -m pytest tests -q --tb=no --junitxml="$tree/upstream.xml") || status=$?
if [ "$status" -gt 1 ]; then exit "$status"; fi
"$python_bin" - "$tree/upstream.xml" <<'PY'
import sys
import xml.etree.ElementTree as ET
known = {
    'test_discovery_schema_and_bare_get_are_bounded',
    'test_omitted_search_mode_defaults_to_hybrid_and_counts_toward_the_semantic_limit',
    'test_every_cli_research_flag_is_a_tool_parameter_and_vice_versa',
    'test_search_papers_is_a_read_only_structured_tool',
    'test_paper_info_and_reading_use_stable_schemas_and_opaque_continuation',
    'test_taxonomy_and_benchmark_tools_return_stable_catalog_entities',
    'test_new_catalog_tools_return_the_cli_json_document',
    'test_resources_expose_canonical_papers_tasks_and_benchmarks',
    'test_paper_tools_fall_back_to_public_metadata_outside_the_catalog',
    'test_a_reference_the_public_metadata_api_finds_in_the_catalog_returns_the_catalog_paper',
}
cases = list(ET.parse(sys.argv[1]).iter('testcase'))
failed = {c.attrib['name'] for c in cases if c.find('failure') is not None or c.find('error') is not None}
assert not failed - known, f'New upstream failures: {failed - known}'
assert len(cases) >= 91 and not any(c.find('skipped') is not None for c in cases)
assert len(cases) - len(failed) >= 81
print(f'Upstream baseline preserved: {len(cases)-len(failed)} passed, {len(failed)} known failures.')
PY
printf 'Patched tree and test output: %s\n' "$tree"
