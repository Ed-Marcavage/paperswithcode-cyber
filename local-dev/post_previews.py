"""Preview images for industry posts: page screenshot, else publisher artwork, else a title card.

The screenshot is the top 1280x1760 CSS pixels of the post page at a 1280x900
viewport, scaled down to the 400x550 card (no crop), saved as JPEG quality 85.
It is taken by `post_screenshot.mjs` (Node + Playwright + Chromium), one page
at a time, with one retry after a load failure, HTTP 429 or 5xx. Consent banners
and dimming layers are removed before capture. A capture is rejected when:

- the page did not load, or answered with HTTP 400 or above;
- it is a challenge or block page: a `cf-mitigated: challenge` header, a known
  challenge widget in the DOM (Cloudflare, PerimeterX, DataDome, Incapsula,
  hCaptcha, reCAPTCHA), challenge wording in the title, or challenge wording
  in a page with under 3,000 characters of text;
- the image is mostly blank: at least 92% of the card's pixels have a grey
  level within 8 of the most common grey level. Real post pages measured
  0.37-0.84 on this test in the pilot.

Bot challenges are never worked around. Requires Node on PATH and a Playwright
package with a Chromium build (see `check_browser`).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from io import BytesIO
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
from typing import Callable, Optional

from PIL import Image

CARD_SIZE = (400, 550)
CAPTURE_SIZE = (1280, 1760)
JPEG_QUALITY = 85
BLANK_TOLERANCE = 8
BLANK_SHARE = 0.92
SHORT_PAGE_CHARS = 3000
RETRY_PAUSE_SECONDS = 3
CAPTURE_TIMEOUT_SECONDS = 90
SCRIPT = Path(__file__).with_name("post_screenshot.mjs")
CHALLENGE_TEXT = re.compile(
    r"just a moment|verify you are (a )?human|checking (if the site connection is secure|your browser)"
    r"|attention required|access denied|are you a robot|press (&|and) hold|captcha|unusual traffic"
    r"|request (was )?blocked|enable javascript and cookies to continue|pardon our interruption",
    re.I,
)

METHOD_SCREENSHOT = "screenshot"
METHOD_ARTWORK = "artwork"
METHOD_TITLE_CARD = "title card"


class BrowserMissing(RuntimeError):
    pass


def check_browser() -> str:
    """Return the Chromium executable the screenshot script will use, or raise BrowserMissing."""
    node = shutil.which("node")
    if node is None:
        raise BrowserMissing("Screenshots need Node.js on PATH (node).")
    module = os.environ.get("PWC_PLAYWRIGHT_CORE", "playwright-core")
    probe = subprocess.run(
        [node, "-e", "const {chromium} = require(process.argv[1]); console.log(chromium.executablePath())", module],
        capture_output=True, text=True, cwd=SCRIPT.parent,
    )
    if probe.returncode != 0:
        raise BrowserMissing(
            f"Cannot load Playwright from {module!r}. Set PWC_PLAYWRIGHT_CORE to a playwright-core "
            "package directory (for example one in ~/.npm/_npx/*/node_modules/playwright-core)."
        )
    executable = os.environ.get("PWC_CHROMIUM") or probe.stdout.strip()
    if not Path(executable).is_file():
        raise BrowserMissing(
            f"Chromium not found at {executable}. Set PWC_CHROMIUM to an installed Chromium "
            "(for example ~/Library/Caches/ms-playwright/chromium-1217/...); this tool never downloads one."
        )
    return executable


def run_capture(url: str, png_path: Path) -> dict:
    """One page load and capture in a fresh browser; returns the script's report."""
    try:
        done = subprocess.run(["node", str(SCRIPT), url, str(png_path)], capture_output=True, text=True,
                              timeout=CAPTURE_TIMEOUT_SECONDS, cwd=SCRIPT.parent)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"capture took over {CAPTURE_TIMEOUT_SECONDS} s"}
    lines = done.stdout.strip().splitlines()
    if done.returncode != 0 or not lines:
        return {"ok": False, "error": (done.stderr.strip().splitlines() or ["no output"])[-1][:300]}
    return json.loads(lines[-1])


def challenge_reason(report: dict) -> Optional[str]:
    if report.get("cf_mitigated") == "challenge":
        return "challenge page (cf-mitigated header)"
    if report.get("challenge_markers"):
        return "challenge page (" + report["challenge_markers"][0] + ")"
    title = report.get("title") or ""
    if CHALLENGE_TEXT.search(title):
        return f"challenge page (title: {title[:60]})"
    if report.get("text_length", 0) < SHORT_PAGE_CHARS and CHALLENGE_TEXT.search(report.get("text_head") or ""):
        return "challenge page (short page with challenge wording)"
    return None


def load_reason(report: dict) -> Optional[str]:
    """Why the page load itself is unusable, or None."""
    if not report.get("ok"):
        return "load failed: " + (report.get("error") or "unknown error")
    status = report.get("status")
    if status is not None and status >= 400:
        return f"HTTP {status}"
    return challenge_reason(report)


def retryable(report: dict) -> bool:
    status = report.get("status")
    return not report.get("ok") or status == 429 or (status is not None and status >= 500)


def to_card(capture: Image.Image) -> Image.Image:
    """Scale the full-width top of the page to the card; pad a short page with white."""
    width, height = CAPTURE_SIZE
    top = capture.convert("RGB").crop((0, 0, width, min(height, capture.height)))
    if top.size != CAPTURE_SIZE:
        canvas = Image.new("RGB", CAPTURE_SIZE, "white")
        canvas.paste(top, (0, 0))
        top = canvas
    return top.resize(CARD_SIZE, Image.Resampling.LANCZOS)


def blank_share(image: Image.Image) -> float:
    """Share of pixels whose grey level is within BLANK_TOLERANCE of the most common grey level."""
    histogram = image.convert("L").histogram()
    peak = max(range(256), key=histogram.__getitem__)
    near = sum(histogram[max(0, peak - BLANK_TOLERANCE): peak + BLANK_TOLERANCE + 1])
    return near / sum(histogram)


def jpeg_bytes(image: Image.Image) -> bytes:
    buffer = BytesIO()
    image.convert("RGB").save(buffer, "JPEG", quality=JPEG_QUALITY)
    return buffer.getvalue()


@dataclass
class Screenshot:
    image: Optional[Image.Image]
    rejected: Optional[str]
    attempts: list = field(default_factory=list)
    blank_share: Optional[float] = None


def _attempt_summary(report: dict) -> dict:
    keep = ("ok", "status", "final_url", "title", "text_length", "seconds", "error", "removed", "captured_height")
    return {key: report[key] for key in keep if key in report}


def take_screenshot(url: str, capture: Callable[[str, Path], dict] = run_capture,
                    pause: Callable[[float], None] = time.sleep) -> Screenshot:
    """Screenshot one post page as a card image, or say why not."""
    attempts = []
    with tempfile.TemporaryDirectory() as directory:
        png = Path(directory) / "page.png"
        for attempt in (1, 2):
            report = capture(url, png)
            attempts.append(_attempt_summary(report))
            if attempt == 1 and retryable(report):
                pause(RETRY_PAUSE_SECONDS)
                continue
            break
        reason = load_reason(report)
        if reason:
            return Screenshot(None, reason, attempts)
        with Image.open(png) as raw:
            card = to_card(raw)
    share = blank_share(card)
    if share >= BLANK_SHARE:
        return Screenshot(None, f"mostly blank ({share:.0%} near-uniform pixels)", attempts, round(share, 3))
    return Screenshot(card, None, attempts, round(share, 3))


def artwork_service():
    """The ThumbnailService methods used here need only `thumbnail_width`.

    Its __init__ reads settings, creates cache directories and an HF client,
    which this host-side tool does not need."""
    from backend.services.thumbnail_service import EXPECTED_THUMBNAIL_WIDTH, ThumbnailService

    service = object.__new__(ThumbnailService)
    service.thumbnail_width = EXPECTED_THUMBNAIL_WIDTH
    return service


async def publisher_artwork(service, url: str) -> tuple[Optional[Image.Image], Optional[str]]:
    """Publisher artwork composed on a card, or (None, note)."""
    from backend.services.thumbnail_service import ThumbnailGenerationError, compose_artwork_thumbnail

    try:
        artwork = await service._fetch_external_artwork(url)
    except ThumbnailGenerationError as exc:  # transient fetch failure; the title card stands in
        return None, f"artwork fetch failed: {exc}"
    if artwork is None:
        return None, "no usable publisher artwork"
    return compose_artwork_thumbnail(artwork), None


async def prepare_preview(url: str, title: Optional[str], shoot: Callable[[str], Screenshot],
                          artwork, title_card) -> tuple[Image.Image, dict]:
    """Screenshot first; if rejected, publisher artwork; if none, the title card.

    `artwork(url)` is awaited and returns (image or None, note); `title_card(title, url)`
    returns an image (with no title given, the page title the browser saw, if any).
    Returns the image and a record of how it was made."""
    shot = shoot(url)
    record = {"method": None, "screenshot_rejected": shot.rejected, "artwork_note": None,
              "blank_share": shot.blank_share, "attempts": shot.attempts}
    if shot.image is not None:
        record["method"] = METHOD_SCREENSHOT
        return shot.image, record
    image, note = await artwork(url)
    record["artwork_note"] = note
    if image is not None:
        record["method"] = METHOD_ARTWORK
        return image, record
    record["method"] = METHOD_TITLE_CARD
    page_title = next((a["title"] for a in reversed(shot.attempts) if a.get("title")), None)
    return title_card(title or page_title, url), record


def default_preparer(use_screenshots: bool = True):
    """A `prepare(url, title)` coroutine with the real screenshot, artwork and title card."""
    if use_screenshots:
        check_browser()
    service = artwork_service()

    def skipped(url):
        return Screenshot(None, "screenshots turned off")

    async def prepare(url, title):
        return await prepare_preview(
            url, title, take_screenshot if use_screenshots else skipped,
            lambda page: publisher_artwork(service, page),
            service._render_external_metadata_thumbnail,
        )

    return prepare
