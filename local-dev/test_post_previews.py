"""Post preview selection without a browser: fallback order, rejection tests and the refresh manifest."""
import asyncio
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from PIL import Image, ImageDraw
import pytest

import post_previews as pp
import refresh_post_previews as refresh


@pytest.fixture(autouse=True)
def public_dns(monkeypatch):
    import socket
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443)),
    ])


def page_image(size=(1280, 1760), lines=40, background="white"):
    """A synthetic article: a header bar and lines of 'text' on a plain background."""
    image = Image.new("RGB", size, background)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, size[0], 80), fill="#111827")
    for n in range(lines):
        y = 140 + n * 40
        draw.rectangle((120, y, 120 + (700 if n % 3 else 500), y + 14), fill="#333333")
    return image


def report(**fields):
    return {"ok": True, "status": 200, "title": "A post", "text_length": 12000, "text_head": "Article text",
            "challenge_markers": [], "cf_mitigated": None, **fields}


def fake_capture(reports, image=None):
    """A capture function that returns the given reports in turn and writes `image` as the PNG."""
    calls = []

    def capture(url, png):
        calls.append(url)
        current = reports[len(calls) - 1]
        if current.get("ok"):
            (image or page_image()).save(png)
        return current

    return capture, calls


class BlankTest(unittest.TestCase):
    def test_uniform_images_are_blank(self):
        for colour in ("white", "black", "#1e293b"):
            with self.subTest(colour=colour):
                self.assertGreaterEqual(pp.blank_share(Image.new("RGB", pp.CARD_SIZE, colour)), pp.BLANK_SHARE)

    def test_faint_gradient_within_tolerance_is_blank(self):
        image = Image.new("L", pp.CARD_SIZE)
        image.putdata([250 + (i % 400) * 5 // 400 for i in range(400 * 550)])
        self.assertGreaterEqual(pp.blank_share(image), pp.BLANK_SHARE)

    def test_header_only_page_is_blank(self):
        self.assertGreaterEqual(pp.blank_share(pp.to_card(page_image(lines=0))), pp.BLANK_SHARE)

    def test_text_page_is_not_blank(self):
        self.assertLess(pp.blank_share(pp.to_card(page_image())), pp.BLANK_SHARE)
        self.assertLess(pp.blank_share(pp.to_card(page_image(background="#0b0b0b"))), pp.BLANK_SHARE)


class CardTest(unittest.TestCase):
    def test_full_width_is_scaled_not_cropped(self):
        image = page_image()
        ImageDraw.Draw(image).rectangle((1260, 0, 1279, 1759), fill="red")
        card = pp.to_card(image)
        self.assertEqual(card.size, (400, 550))
        r, g, b = card.getpixel((398, 300))
        self.assertGreater(r, 200)
        self.assertLess(g, 60)

    def test_short_page_is_padded_with_white(self):
        card = pp.to_card(Image.new("RGB", (1280, 900), "black"))
        self.assertEqual(card.size, (400, 550))
        self.assertEqual(card.getpixel((200, 100)), (0, 0, 0))
        self.assertEqual(card.getpixel((200, 500)), (255, 255, 255))

    def test_long_capture_keeps_only_the_top(self):
        image = Image.new("RGB", (1280, 3000), "white")
        ImageDraw.Draw(image).rectangle((0, 1800, 1279, 2999), fill="black")
        self.assertEqual(pp.to_card(image).getpixel((200, 545)), (255, 255, 255))


class RejectionTest(unittest.TestCase):
    def test_http_errors(self):
        self.assertEqual(pp.load_reason(report(status=404)), "HTTP 404")
        self.assertEqual(pp.load_reason(report(status=503)), "HTTP 503")
        self.assertIsNone(pp.load_reason(report(status=None)))

    def test_load_failure(self):
        self.assertEqual(pp.load_reason({"ok": False, "error": "Timeout 30000ms"}), "load failed: Timeout 30000ms")

    def test_challenge_pages(self):
        cases = [
            report(cf_mitigated="challenge"),
            report(challenge_markers=["#px-captcha"]),
            report(title="Just a moment..."),
            report(text_length=300, text_head="Please verify you are human by completing the action below."),
        ]
        for case in cases:
            with self.subTest(case=case):
                self.assertTrue(pp.load_reason(case).startswith("challenge page"))

    def test_captcha_widget_counts_only_on_a_short_page(self):
        widget = ["iframe[src*='recaptcha']"]
        self.assertIsNone(pp.load_reason(report(text_length=18000, challenge_markers=widget)))
        self.assertTrue(pp.load_reason(report(text_length=200, challenge_markers=widget)).startswith("challenge"))

    def test_long_article_about_captchas_is_not_a_challenge(self):
        self.assertIsNone(pp.load_reason(report(text_length=15000, text_head="How attackers solve CAPTCHA with agents")))


class TakeScreenshotTest(unittest.TestCase):
    def test_success_on_first_attempt(self):
        capture, calls = fake_capture([report()])
        shot = pp.take_screenshot("https://example.com/p", capture, pause=lambda s: None)
        self.assertIsNone(shot.rejected)
        self.assertEqual(shot.image.size, (400, 550))
        self.assertEqual(len(calls), 1)

    def test_one_retry_after_a_load_failure(self):
        capture, calls = fake_capture([{"ok": False, "error": "net::ERR_CONNECTION_RESET"}, report()])
        shot = pp.take_screenshot("https://example.com/p", capture, pause=lambda s: None)
        self.assertIsNone(shot.rejected)
        self.assertEqual(len(calls), 2)

    def test_at_most_one_retry(self):
        capture, calls = fake_capture([report(status=502), report(status=503), report()])
        shot = pp.take_screenshot("https://example.com/p", capture, pause=lambda s: None)
        self.assertEqual(shot.rejected, "HTTP 503")
        self.assertEqual(len(calls), 2)

    def test_no_retry_for_a_block_or_challenge(self):
        for first in (report(status=403), report(title="Attention Required! | Cloudflare")):
            capture, calls = fake_capture([first, report()])
            shot = pp.take_screenshot("https://example.com/p", capture, pause=lambda s: None)
            self.assertIsNone(shot.image)
            self.assertEqual(len(calls), 1)

    def test_blank_capture_is_rejected(self):
        capture, _ = fake_capture([report()], image=Image.new("RGB", (1280, 1760), "white"))
        shot = pp.take_screenshot("https://example.com/p", capture, pause=lambda s: None)
        self.assertIsNone(shot.image)
        self.assertTrue(shot.rejected.startswith("mostly blank (100%"))


class FallbackOrderTest(unittest.TestCase):
    def run_prepare(self, shot, artwork_image, title=None):
        artwork_calls, title_calls = [], []

        async def artwork(url):
            artwork_calls.append(url)
            return artwork_image, None if artwork_image else "no usable publisher artwork"

        def title_card(title, url):
            title_calls.append(title)
            return Image.new("RGB", pp.CARD_SIZE, "white")

        image, record = asyncio.run(pp.prepare_preview("https://example.com/p", title, lambda url: shot,
                                                       artwork, title_card))
        return image, record, artwork_calls, title_calls

    def test_screenshot_first(self):
        card = Image.new("RGB", pp.CARD_SIZE, "blue")
        image, record, artwork_calls, title_calls = self.run_prepare(pp.Screenshot(card, None), None)
        self.assertIs(image, card)
        self.assertEqual(record["method"], "screenshot")
        self.assertEqual((artwork_calls, title_calls), ([], []))

    def test_artwork_when_the_screenshot_is_rejected(self):
        art = Image.new("RGB", pp.CARD_SIZE, "green")
        image, record, _, title_calls = self.run_prepare(pp.Screenshot(None, "HTTP 403"), art)
        self.assertIs(image, art)
        self.assertEqual((record["method"], record["screenshot_rejected"]), ("artwork", "HTTP 403"))
        self.assertEqual(title_calls, [])

    def test_title_card_last_with_the_page_title_when_none_given(self):
        shot = pp.Screenshot(None, "mostly blank (99% near-uniform pixels)", [{"ok": True, "title": "Page title"}])
        _, record, artwork_calls, title_calls = self.run_prepare(shot, None)
        self.assertEqual(record["method"], "title card")
        self.assertEqual(record["artwork_note"], "no usable publisher artwork")
        self.assertEqual(artwork_calls, ["https://example.com/p"])
        self.assertEqual(title_calls, ["Page title"])
        _, _, _, title_calls = self.run_prepare(shot, None, title="Catalog title")
        self.assertEqual(title_calls, ["Catalog title"])


class BrowserCheckTest(unittest.TestCase):
    def test_missing_node_is_a_clear_error(self):
        with mock.patch("shutil.which", return_value=None), self.assertRaises(pp.BrowserMissing):
            pp.check_browser()

    def test_unloadable_playwright_is_a_clear_error(self):
        failed = mock.Mock(returncode=1, stdout="", stderr="Cannot find module")
        with mock.patch("shutil.which", return_value="/usr/bin/node"), \
                mock.patch("subprocess.run", return_value=failed), \
                self.assertRaisesRegex(pp.BrowserMissing, "PWC_PLAYWRIGHT_CORE"):
            pp.check_browser()

    def test_missing_chromium_is_a_clear_error(self):
        found = mock.Mock(returncode=0, stdout="/nowhere/chrome\n", stderr="")
        with mock.patch("shutil.which", return_value="/usr/bin/node"), \
                mock.patch("subprocess.run", return_value=found), \
                mock.patch.dict("os.environ", {"PWC_CHROMIUM": ""}), \
                self.assertRaisesRegex(pp.BrowserMissing, "never downloads"):
            pp.check_browser()


class ManifestTest(unittest.TestCase):
    def test_items_are_ids_or_urls(self):
        self.assertEqual(refresh.parse_item("1008")["paper_id"], 1008)
        self.assertEqual(refresh.parse_item("https://example.com/p")["url"], "https://example.com/p")
        self.assertEqual(refresh.parse_item("ftp://example.com/p")["url"], "ftp://example.com/p")

    def test_entry_records_file_digest_and_method(self):
        data = b"jpeg bytes"
        post = {"item": "1008", "paper_id": 1008, "url": "https://example.com/p", "title": "T"}
        entry = refresh.manifest_entry(post, data, {"method": "artwork", "screenshot_rejected": "HTTP 403"})
        self.assertEqual(entry["file"], "1008.jpg")
        self.assertEqual(entry["digest"], sha256(data).hexdigest())
        self.assertEqual((entry["method"], entry["screenshot_rejected"]), ("artwork", "HTTP 403"))
        url_entry = refresh.manifest_entry({**post, "item": post["url"], "paper_id": None}, data, {})
        self.assertRegex(url_entry["file"], r"^[0-9a-f]{20}\.jpg$")

    def test_shoot_writes_jpegs_and_manifest(self):
        async def preparer(url, title):
            return Image.new("RGB", pp.CARD_SIZE, "white"), {"method": "title card", "screenshot_rejected": "HTTP 404"}

        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(refresh, "default_preparer", return_value=preparer):
            output = Path(directory) / "out"
            asyncio.run(refresh.shoot(["https://example.com/p"], output, "http://unused"))
            manifest = json.loads((output / "manifest.json").read_text())
            entry, = manifest["posts"]
            self.assertEqual(manifest["version"], 1)
            self.assertEqual(sha256((output / entry["file"]).read_bytes()).hexdigest(), entry["digest"])
            with self.assertRaises(FileExistsError):
                asyncio.run(refresh.shoot(["https://example.com/p"], output, "http://unused"))


if __name__ == "__main__":
    unittest.main()
