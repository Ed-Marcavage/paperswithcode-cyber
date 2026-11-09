"""Collect public GitHub owner/contributor snapshots for repositories in a local catalog."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import sys
from urllib.request import urlopen


def github(endpoint, *flags):
    output = subprocess.check_output(["gh", "api", endpoint, *flags], timeout=120)
    return json.loads(output or "[]")


def collect(full_name):
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", full_name, re.ASCII):
        raise ValueError(f"Invalid GitHub repository: {full_name}")
    repo = github(f"repos/{full_name}")
    if repo["private"]:
        raise ValueError(f"Repository is private: {full_name}")
    observed = datetime.now(timezone.utc).isoformat()
    users = {}
    owner = repo["owner"]
    if owner["type"] == "User":
        users[owner["id"]] = dict(id=owner["id"], login=owner["login"], owns=True, commits=0)
    pages = github(f"repos/{repo['full_name']}/contributors?per_page=100", "--paginate", "--slurp")
    for page in pages:
        for user in page or []:
            if user["type"] == "User" and user["contributions"] > 0:
                users[user["id"]] = dict(id=user["id"], login=user["login"],
                                         owns=user["id"] == owner["id"], commits=user["contributions"])
    return dict(catalog_name=full_name, github_repo_id=repo["id"], full_name=repo["full_name"],
                observed_at=observed, users=list(users.values()))


def tracked(api):
    names = set()
    page = 1
    while page:
        with urlopen(f"{api}/repositories/?page_size=100&page={page}", timeout=30) as response:
            data = json.load(response)
        names.update(f"{r['owner']}/{r['name']}" for r in data["results"])
        page = data["next_page"]
    return sorted(names)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--api", default="http://localhost:8095/api/v1")
    args = parser.parse_args()
    records, failures = [], []
    with ThreadPoolExecutor(max_workers=3) as pool:
        jobs = [(name, pool.submit(collect, name)) for name in tracked(args.api)]
        for name, job in jobs:
            try:
                records.append(job.result())
            except (subprocess.SubprocessError, ValueError) as exc:
                failures.append(name)
                print(f"{name}: {exc}", file=sys.stderr)
    with args.output.open("x") as out:
        json.dump(records, out)
    print(f"Collected {len(records)} repositories; failed {len(failures)}.")
    return bool(failures)


if __name__ == "__main__":
    sys.exit(main())
