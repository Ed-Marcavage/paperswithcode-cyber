"""Local assistant maintenance. Run with ``python -m backend.assistant_cli``."""

import argparse
import json

from backend.assistant_config import get_assistant_settings
from backend.services.assistant_store import get_assistant_store, ConversationNotFound


def main(argv=None, *, store=None):
    parser = argparse.ArgumentParser(description="Cyber assistant maintenance")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("purge", help="Delete conversations older than the configured retention")
    for command in ("list", "export"):
        sub = commands.add_parser(command, help="Read runs without calling a model")
        sub.add_argument("--days", type=int, default=7)
    show = commands.add_parser("show", help="Read a complete run trace in order")
    show.add_argument("run_id")
    args = parser.parse_args(argv)
    if getattr(args, "days", 1) < 1:
        parser.error("--days must be positive")
    store = store or get_assistant_store()
    if args.command == "purge":
        count = store.purge(get_assistant_settings().retention_days)
        print(f"Deleted {count} expired conversations.")
    elif args.command == "show":
        try:
            run = store.show_run(args.run_id)
        except ConversationNotFound:
            parser.error("Run not found")
        print(f"Run {run['id']} | {run['status']} | {run['model']}")
        print(f"Prompt {run['prompt_version']} {run['prompt_hash']}")
        print(f"Asked from {run['surface']} at {run['site_path']}")
        print(f"Topic: {run['topic'] or 'none'}")
        print(f"Question: {run['question']}")
        for position, step in enumerate(run["steps"], 1):
            print(f"\nStep {position}: {step['kind']}")
            print(json.dumps(step, ensure_ascii=False, indent=2))
        print(f"\nAnswer: {run['answer']}")
        print(f"Error: {run['error']}\nFeedback: {json.dumps(run['feedback'], ensure_ascii=False)}")
    else:
        for run in store.runs(args.days):
            if args.command == "export":
                print(json.dumps(run, ensure_ascii=False))
            else:
                print(json.dumps({key: value for key, value in run.items() if key not in {"answer", "steps"}}
                                 | {"steps": len(run["steps"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
