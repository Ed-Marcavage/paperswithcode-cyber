"""Prepare publisher previews for a reviewed local bundle before metadata import."""

import argparse
import asyncio
from hashlib import sha256
import json
from pathlib import Path
import shutil

from backend.services.thumbnail_service import (
    ThumbnailService,
    compose_artwork_thumbnail,
)


async def prepare(source, output):
    if output.exists():
        raise FileExistsError(output)
    shutil.copytree(source, output)
    catalog_path = output / "catalog.json"
    catalog = json.loads(catalog_path.read_text())
    service = ThumbnailService()
    for row in catalog["rows"]:
        if row["kind"] != "post":
            continue
        artwork = await service._fetch_external_artwork(row["url"])
        if artwork is None:
            thumbnail = service._render_external_metadata_thumbnail(
                row["title"], row["url"]
            )
            mode = "title card"
        else:
            thumbnail = compose_artwork_thumbnail(artwork)
            mode = "publisher artwork"
        row["preview_file"] = (
            "previews/" + sha256(row["id"].encode()).hexdigest() + ".jpg"
        )
        path = output / row["preview_file"]
        path.parent.mkdir(parents=True, exist_ok=True)
        thumbnail.save(path, "JPEG", quality=85)
        print(row["id"], mode, flush=True)
    catalog_path.write_text(json.dumps(catalog, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    asyncio.run(prepare(args.source, args.output))
