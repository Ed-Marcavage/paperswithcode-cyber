// Screenshot the top of one post page with headless Chromium (Playwright).
//
// Usage: node post_screenshot.mjs <url> <out.png>
// Prints one JSON object to stdout describing the page; on success the PNG is
// the top 1280x(up to 1760) CSS pixels of the page at a 1280x900 viewport.
// Called by post_previews.py, which judges the result and makes the JPEG.
//
// Environment:
//   PWC_PLAYWRIGHT_CORE  path to a playwright-core (or playwright) package
//                        directory; defaults to require("playwright-core").
//   PWC_CHROMIUM         Chromium executable; defaults to the one that
//                        Playwright version expects in ~/Library/Caches/ms-playwright.
//
// Consent banners and dimming layers are removed before capture. Bot challenges
// are reported, never worked around.
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PWC_PLAYWRIGHT_CORE || "playwright-core");

const UA =
  "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36";
const VIEW = { width: 1280, height: 900 };
const CAPTURE_HEIGHT = 1760; // 1280 x 1760 is the 400 x 550 card ratio
const NAVIGATION_TIMEOUT_MS = 30000;
// Settle budget after "load", about 5 s in all: network idle, lazy-image scroll, final paint.
const NETWORK_IDLE_MS = 2500;
const SCROLL_STEP_MS = 200;
const FINAL_PAUSE_MS = 1000;

const [, , url, outPath] = process.argv;
if (!url || !outPath) {
  console.error("usage: node post_screenshot.mjs <url> <out.png>");
  process.exit(2);
}

// Runs in the page. Finds and removes consent banners and dimming layers.
const CLEAN = () => {
  const consent = /cookie|consent|gdpr|your privacy|privacy (choices|preferences|settings|center)|accept all|reject all/i;
  const consentFrame = /consent|cookie|privacy|onetrust|trustarc|sourcepoint|cookiebot|didomi|usercentrics/i;
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  const removed = [];
  const translucent = (cs) => {
    if (parseFloat(cs.opacity) < 1) return true;
    const m = cs.backgroundColor.match(/rgba?\(([^)]+)\)/);
    if (!m) return false;
    const parts = m[1].split(/[ ,/]+/).filter(Boolean);
    const alpha = parts.length > 3 ? parseFloat(parts[3]) : 1;
    return alpha > 0.05 && alpha < 0.95;
  };
  for (const el of Array.from(document.querySelectorAll("body *"))) {
    if (!el.isConnected) continue;
    const cs = getComputedStyle(el);
    if (cs.position !== "fixed" && cs.position !== "sticky") continue;
    if (cs.display === "none" || cs.visibility === "hidden") continue;
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) continue;
    const text = (el.innerText || "").trim().replace(/\s+/g, " ");
    let why = null;
    if (text.length < 2000 && consent.test(text)) why = "consent text";
    else if (el.tagName === "IFRAME" && consentFrame.test(el.src || "")) why = "consent frame";
    else if (cs.position === "fixed" && r.width >= vw * 0.9 && r.height >= vh * 0.9 && text.length < 200 && translucent(cs))
      why = "dimming layer";
    if (why) {
      removed.push({ why, tag: el.tagName.toLowerCase(), w: Math.round(r.width), h: Math.round(r.height), text: text.slice(0, 80) });
      el.remove();
    }
  }
  // Some consent managers (Usercentrics, for one) render inside a shadow root,
  // which the scan above cannot see into; remove such a host by its shadow text.
  for (const host of Array.from(document.querySelectorAll("body *")).filter((el) => el.shadowRoot)) {
    let text = ""; // visible text only: shadow roots often inline large <style> blocks
    for (const node of host.shadowRoot.querySelectorAll("*")) {
      if (node.tagName === "STYLE" || node.tagName === "SCRIPT") continue;
      for (const child of node.childNodes) if (child.nodeType === Node.TEXT_NODE) text += child.textContent + " ";
    }
    text = text.trim().replace(/\s+/g, " ");
    if (text.length < 5000 && consent.test(text)) {
      removed.push({ why: "consent text (shadow root)", tag: host.tagName.toLowerCase(), text: text.slice(0, 80) });
      host.remove();
    }
  }
  if (removed.length) {
    // Consent managers often lock scrolling; unlock so the full-page capture works.
    for (const node of [document.documentElement, document.body]) {
      const cs = getComputedStyle(node);
      if (cs.overflowY === "hidden") node.style.setProperty("overflow", "visible", "important");
      if (cs.position === "fixed") node.style.setProperty("position", "static", "important");
    }
  }
  return removed;
};

// Runs in the page. Signals used to reject challenge or block pages.
const PROBE = () => {
  const text = (document.body?.innerText || "").trim();
  const markers = [
    "iframe[src*='challenges.cloudflare.com']", "#challenge-form", "#cf-challenge-running", "#challenge-running",
    "#px-captcha", "iframe[src*='captcha-delivery.com']", "script[src*='captcha-delivery.com']",
    "iframe[src*='_Incapsula_Resource']", "iframe[src*='hcaptcha.com']", "iframe[src*='recaptcha']",
  ].filter((selector) => document.querySelector(selector));
  return {
    title: document.title,
    text_length: text.length,
    text_head: text.slice(0, 3000),
    challenge_markers: markers,
    doc_height: document.documentElement.scrollHeight,
  };
};

const result = { url };
const browser = await chromium.launch({
  headless: true,
  ...(process.env.PWC_CHROMIUM ? { executablePath: process.env.PWC_CHROMIUM } : {}),
});
try {
  const context = await browser.newContext({ viewport: VIEW, userAgent: UA, locale: "en-US", deviceScaleFactor: 1 });
  const page = await context.newPage();
  const started = Date.now();
  try {
    const response = await page.goto(url, { waitUntil: "load", timeout: NAVIGATION_TIMEOUT_MS });
    result.status = response ? response.status() : null;
    result.cf_mitigated = response ? (await response.allHeaders())["cf-mitigated"] || null : null;
    result.final_url = page.url();
    await page.waitForLoadState("networkidle", { timeout: NETWORK_IDLE_MS }).catch(() => {});
    for (let y = 0; y <= CAPTURE_HEIGHT; y += 450) {
      await page.evaluate((top) => window.scrollTo(0, top), y);
      await page.waitForTimeout(SCROLL_STEP_MS);
    }
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.waitForTimeout(FINAL_PAUSE_MS);
    result.removed = await page.evaluate(CLEAN);
    Object.assign(result, await page.evaluate(PROBE));
    const height = Math.min(CAPTURE_HEIGHT, Math.max(VIEW.height, result.doc_height));
    await page.screenshot({ path: outPath, fullPage: true, clip: { x: 0, y: 0, width: VIEW.width, height } });
    result.captured_height = height;
    result.ok = true;
  } catch (error) {
    result.ok = false;
    result.error = String(error.message || error).split("\n")[0];
  }
  result.seconds = (Date.now() - started) / 1000;
} finally {
  await browser.close();
}
process.stdout.write(JSON.stringify(result) + "\n");
