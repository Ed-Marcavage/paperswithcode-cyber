"""Local assistant maintenance. Run with ``python -m backend.assistant_cli``."""

import argparse

from backend.assistant_config import get_assistant_settings
from backend.services.assistant_store import get_assistant_store


def main(argv=None, *, store=None):
    parser = argparse.ArgumentParser(description="Cyber assistant maintenance")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("purge", help="Delete conversations older than the configured retention")
    parser.parse_args(argv)
    count = (store or get_assistant_store()).purge(get_assistant_settings().retention_days)
    print(f"Deleted {count} expired conversations.")


if __name__ == "__main__":
    main()
