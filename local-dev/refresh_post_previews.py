"""Refresh preview images for industry posts already in the catalog: files only.

`shoot` takes post ids (native paper ids) or post URLs and writes, to a new
output folder, one 400x550 JPEG per post and `manifest.json` with how each image
was made (screenshot, artwork or title card) and why a screenshot was rejected.
Ids are resolved to their URL and title through the catalog API (`--api`).
`sheet` draws a contact sheet of the chosen images at card size.

Nothing here touches the database; `load_post_previews.py` loads a manifest
into `discovery_previews`, as a separate step. Run on the host (see
"Post preview images" in local-dev/README.md).
"""
import argparse
import asyncio
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sys
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
from post_previews import default_preparer, jpeg_bytes  # noqa: E402

MANIFEST_VERSION = 1
SHEET_CARD = (160, 220)  # the card's thumbnail size on the site


def parse_item(item: str) -> dict:
    """A numeric id or supplied URL; the preparer records unsafe URLs as rejected."""
    if item.isdigit():
        return {"item": item, "paper_id": int(item), "url": None, "title": None}
    parsed = urlparse(item)
    if not parsed.scheme:
        raise ValueError(f"Expected a paper id or a URL: {item!r}")
    return {"item": item, "paper_id": None, "url": item, "title": None}


def resolve(post: dict, api: str) -> dict:
    if post["url"] is not None:
        return post
    request = Request(f"{api.rstrip('/')}/api/v1/papers/{post['paper_id']}", headers={"Accept": "application/json"})
    with urlopen(request, timeout=30) as response:
        paper = json.load(response)
    if not paper.get("source_url"):
        raise ValueError(f"Paper {post['paper_id']} has no source URL")
    return {**post, "url": paper["source_url"], "title": paper.get("title")}


def file_name(post: dict) -> str:
    if post["paper_id"] is not None:
        return f"{post['paper_id']}.jpg"
    return sha256(post["url"].encode()).hexdigest()[:20] + ".jpg"


def manifest_entry(post: dict, data: bytes, record: dict) -> dict:
    return {**post, "file": file_name(post), "digest": sha256(data).hexdigest(), **record}


def write_manifest(output: Path, entries: list) -> None:
    manifest = {"version": MANIFEST_VERSION, "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "posts": entries}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")


async def shoot(items: list, output: Path, api: str, use_screenshots: bool = True) -> list:
    posts = [parse_item(item) for item in items]
    if output.exists():
        raise FileExistsError(output)
    preparer = default_preparer(use_screenshots)  # Shared destination checks cover direct and catalog-derived URLs.
    posts = [resolve(post, api) for post in posts]
    output.mkdir(parents=True)
    entries = []
    for post in posts:
        image, record = await preparer(post["url"], post["title"])
        data = jpeg_bytes(image)
        entry = manifest_entry(post, data, record)
        (output / entry["file"]).write_bytes(data)
        entries.append(entry)
        write_manifest(output, entries)  # after every post, so a stopped run keeps its work
        print(post["item"], record["method"], record["screenshot_rejected"] or "", flush=True)
    return entries


def contact_sheet(output: Path, columns: int = 8) -> Path:
    """The chosen image per post at card size, labelled with id and method."""
    entries = json.loads((output / "manifest.json").read_text())["posts"]
    card_w, card_h = SHEET_CARD
    label_h, gap = 46, 12
    rows = (len(entries) + columns - 1) // columns
    sheet = Image.new("RGB", (gap + columns * (card_w + gap), gap + rows * (card_h + label_h + gap)), "#e5e7eb")
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default(size=12)
    for index, entry in enumerate(entries):
        x = gap + (index % columns) * (card_w + gap)
        y = gap + (index // columns) * (card_h + label_h + gap)
        with Image.open(output / entry["file"]) as image:
            sheet.paste(image.convert("RGB").resize(SHEET_CARD, Image.Resampling.LANCZOS), (x, y))
        draw.rectangle((x - 1, y - 1, x + card_w, y + card_h), outline="#9ca3af")
        host = (urlparse(entry["url"]).hostname or "").removeprefix("www.")
        draw.text((x, y + card_h + 4), f"{entry['paper_id'] or ''} {entry['method']}", fill="#111827", font=font)
        draw.text((x, y + card_h + 20), host[:26], fill="#4b5563", font=font)
    path = output / "contact_sheet.jpg"
    sheet.save(path, "JPEG", quality=90)
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    shoot_parser = commands.add_parser("shoot", help="Write JPEGs and manifest.json for the given posts")
    shoot_parser.add_argument("output", type=Path, help="New folder for the JPEGs and manifest")
    shoot_parser.add_argument("items", nargs="*", help="Paper ids or post URLs")
    shoot_parser.add_argument("--from-file", type=Path, help="One paper id or URL per line")
    shoot_parser.add_argument("--api", default="http://localhost:8095", help="Catalog origin used to resolve ids")
    shoot_parser.add_argument("--no-screenshots", action="store_true",
                              help="Skip page screenshots: publisher artwork, else a title card")
    sheet_parser = commands.add_parser("sheet", help="Draw contact_sheet.jpg for an output folder")
    sheet_parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.command == "shoot":
        items = list(args.items)
        if args.from_file:
            items += [line.strip() for line in args.from_file.read_text().splitlines() if line.strip()]
        if not items:
            parser.error("give paper ids or URLs, or --from-file")
        entries = asyncio.run(shoot(items, args.output, args.api, not args.no_screenshots))
        counts = {}
        for entry in entries:
            counts[entry["method"]] = counts.get(entry["method"], 0) + 1
        print(json.dumps({"posts": len(entries), "methods": counts, "manifest": str(args.output / "manifest.json")}))
    else:
        print(contact_sheet(args.output))


if __name__ == "__main__":
    main()
