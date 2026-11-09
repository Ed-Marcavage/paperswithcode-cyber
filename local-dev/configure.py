"""Create ignored local credentials/configuration without overwriting an existing file."""
import argparse
import os
from pathlib import Path
import secrets

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--port", type=int, default=8095, choices=range(1024, 65536), metavar="PORT")
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
config = {
    "PWC_DB_HOST": "127.0.0.1",
    "CATALOG_PORT": str(args.port),
    "PWC_DISCOVERY_CATALOG": "true",
    "PWC_MCP_CURSOR_KEY_CURRENT": secrets.token_urlsafe(48),
    "PWC_DB_NAME": "pwc_local",
    "PWC_DB_USER": "pwc_local",
    "PWC_DB_PASSWORD": secrets.token_hex(24),
    "PWC_JWT_SECRET": secrets.token_hex(32),
    "PWC_ENVIRONMENT": "development",
    "PWC_HOST": "127.0.0.1",
    "PWC_PORT": "8015",
    "PWC_CHAT_ENABLED": "false",
    "PWC_CRON_ENABLED": "false",
    "PWC_CATALOG_MUTATIONS_ENABLED": "false",
    "PWC_THUMBNAIL_MUTATIONS_ENABLED": "false",
    "PWC_CODEX_JOBS_ENABLED": "false",
    "PWC_CODEX_CURATION_SCHEDULER_ENABLED": "false",
    "PWC_CODEX_CURATION_DIRECT_APPLY_ENABLED": "false",
    "PWC_AUTONOMOUS_SUBMISSION_ENABLED": "false",
    "PWC_PAPER_EDIT_AUTO_APPROVE_ENABLED": "false",
    "PWC_PAPER_MARKDOWN_PAID_DISPATCH_ENABLED": "false",
    "PWC_HF_TOKEN": "",
    "PWC_GITHUB_TOKEN": "",
    "PWC_OPENAI_API_KEY": "",
    "PWC_ANTHROPIC_API_KEY": "",
    "PWC_EXTRA_ALLOWED_ORIGINS": f"http://localhost:{args.port},http://127.0.0.1:{args.port}",
    "VITE_DISABLE_AUTH": "1",
    "VITE_CHAT_ENABLED": "false",
    "VITE_API_URL": "",
    "VITE_POSTHOG_PROJECT_TOKEN": "",
}
path = root / ".local.env"
# Exclusive creation also protects the database password on repeated setup.
with open(path, "x", opener=lambda p, flags: os.open(p, flags, 0o600)) as stream:
    stream.write("".join(f"{key}={value}\n" for key, value in config.items()))
print("Created .local.env (0600); credentials were not printed.")
