import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect, it } from "vitest";

// Visitors clicked the summary text of a Trending row, which did nothing. The row is now one
// target: the title link is stretched over the card and other controls sit above it.
it("makes the whole paper row open the entry while keeping inner links clickable", () => {
  const css = readFileSync(resolve(__dirname, "features/paper-list.css"), "utf8");
  expect(css).toMatch(/\.paper-card\s*\{\s*position:\s*relative;\s*\}/);
  expect(css).toMatch(/\.paper-card \.paper-title > a::after\s*\{[^}]*position:\s*absolute;[^}]*inset:\s*0;/);
  expect(css).toMatch(/\.paper-card :is\(a, button, summary\):not\(\.paper-title > a\)\s*\{[^}]*z-index:\s*1;/);
});
