"""Prepare post previews for a reviewed local bundle before metadata import.

Each post gets a screenshot of its page; if the screenshot is rejected,
publisher artwork; if there is none, a title card (see post_previews.py).
Run on the host: screenshots need Node, Playwright and Chromium, which the
backend container does not have. `--no-screenshots` keeps the earlier
artwork-or-title-card behaviour. `previews/report.json` records, per post, which
method made the image and why a screenshot was rejected.
"""

import argparse
import asyncio
from hashlib import sha256
import json
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))  # also works as python -m local-dev.catalog_post_previews
from post_previews import default_preparer, jpeg_bytes  # noqa: E402


async def prepare(source, output, use_screenshots=True):
    if output.exists():
        raise FileExistsError(output)
    preparer = default_preparer(use_screenshots)  # fails early when the browser is missing
    shutil.copytree(source, output)
    catalog_path = output / "catalog.json"
    catalog = json.loads(catalog_path.read_text())
    report = []
    for row in catalog["rows"]:
        if row["kind"] != "post":
            continue
        thumbnail, record = await preparer(row["url"], row["title"])
        row["preview_file"] = (
            "previews/" + sha256(row["id"].encode()).hexdigest() + ".jpg"
        )
        path = output / row["preview_file"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(jpeg_bytes(thumbnail))
        report.append({"id": row["id"], "url": row["url"], "preview_file": row["preview_file"], **record})
        print(row["id"], record["method"], record["screenshot_rejected"] or "", flush=True)
    catalog_path.write_text(json.dumps(catalog, ensure_ascii=False) + "\n")
    report_path = output / "previews" / "report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--no-screenshots", action="store_true",
                        help="Skip page screenshots: publisher artwork, else a title card")
    args = parser.parse_args()
    asyncio.run(prepare(args.source, args.output, not args.no_screenshots))
