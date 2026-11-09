"""Build a static catalog in a new directory using only public frontend configuration."""
import argparse
import os
from pathlib import Path
import subprocess
from urllib.parse import urlparse

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--output", required=True, type=Path)
parser.add_argument("--site", required=True, help="Canonical HTTPS origin")
parser.add_argument("--config", type=Path, default=root / ".local.env", help="Local dotenv file (optional)")
parser.add_argument("--environment", choices=["preview", "production"], required=True)
args = parser.parse_args()
site = urlparse(args.site)
if site.scheme != "https" or not site.hostname or site.username or site.password or site.path not in ("", "/") or site.query or site.fragment:
    parser.error("--site must be an HTTPS origin")
out = args.output.resolve()
if out.exists():
    parser.error("--output must be a new directory")
public_keys = {"VITE_POSTHOG_PROJECT_TOKEN", "VITE_POSTHOG_HOST"}
values = {key: os.environ.get(key, "") for key in public_keys}
if args.config.exists():
    for line in args.config.read_text().splitlines():
        key, _, value = line.partition("=")
        if key in values and not values[key]:
            values[key] = value.strip().strip("\"'")
if values["VITE_POSTHOG_PROJECT_TOKEN"] and (not values["VITE_POSTHOG_PROJECT_TOKEN"].startswith("phc_") or
        values["VITE_POSTHOG_HOST"] not in {"https://us.i.posthog.com", "https://eu.i.posthog.com"}):
    parser.error("Use a public PostHog project token and its regional ingest host")
env = {k: v for k, v in os.environ.items() if not k.startswith("VITE_")}
env.update(values, VITE_API_URL="", VITE_LOCAL_CATALOG="true", VITE_DISABLE_AUTH="1",
           VITE_CATALOG_ANALYTICS_ENV=args.environment, VITE_CHAT_ENABLED="false", VITE_CHAT_LIVE="false",
           VITE_CHAT_MCP_APPS_HOST_ENABLED="false", VITE_NATIVE_PDF_READER_ENABLED="false",
           VITE_PAPER_READER_CHAT_ENABLED="false", VITE_PAPER_READER_SELECTION_ENABLED="false",
           VITE_CODEX_ADD_EVALS_ENABLED="false", VITE_CODEX_ENRICH_PAPER_ENABLED="false")
subprocess.run(["npm", "run", "build", "--", "--outDir", str(out)], cwd=root / "frontend", env=env, check=True)
index = out / "index.html"
html = index.read_text()
for name in ('property="og:url"', 'property="og:image"', 'name="twitter:image"'):
    html = html.replace(name + ' content="https://paperswithcode.co/', name + ' content="' + args.site.rstrip("/") + '/')
index.write_text(html)
print(f"Built {args.environment} catalog; PostHog {'enabled' if values['VITE_POSTHOG_PROJECT_TOKEN'] else 'disabled'}.")
