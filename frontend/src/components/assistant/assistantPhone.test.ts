import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect, it } from "vitest";

const css = readFileSync(resolve(__dirname, "assistant.css"), "utf8");

it("keeps assistant fields at 16px on touch screens so iOS does not zoom the page on focus", () => {
  expect(css).toMatch(/@media \(max-width: 900px\), \(pointer: coarse\)\s*\{[^}]*\.assistant-page \.assistant-field textarea[^}]*font-size:\s*16px;/s);
});

it("stops the chat page itself from scrolling; only the transcript scrolls", () => {
  expect(css).toMatch(/:root:has\(\.assistant-page-shell\) body\s*\{[^}]*overflow:\s*hidden;[^}]*overscroll-behavior:\s*none;/s);
  expect(css).toMatch(/\.assistant-page-shell\s*\{[^}]*max-width:\s*100vw;[^}]*overflow:\s*hidden;/s);
});

it("hides the header's Ask button on phones", () => {
  expect(css).toMatch(/@media \(max-width: 640px\)\s*\{\s*\.assistant-ask-trigger\s*\{\s*display:\s*none;\s*\}/s);
});
