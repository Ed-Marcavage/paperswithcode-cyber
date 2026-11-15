import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect, it } from "vitest";

// jsdom does not lay pages out, so the phone pass (Playwright, scrollWidth == clientWidth on
// every assistant surface at 360-430 px) is the real check. These rules are what keep answers
// from widening the page; this test fails if one of them is removed.
const css = readFileSync(resolve(process.cwd(), "src/components/assistant/assistant.css"), "utf8").replace(/\s+/g, " ");
const rule = (selector: string) => {
  const start = css.indexOf(selector + " {");
  expect(start, `missing rule ${selector}`).toBeGreaterThanOrEqual(0);
  return css.slice(start, css.indexOf("}", start));
};

it("keeps long answer text, links, tables and code inside the column on phones", () => {
  expect(rule(".assistant-message")).toContain("overflow-wrap: anywhere");
  expect(rule(".assistant-table")).toMatch(/max-width: 100%;.*overflow-x: auto/);
  expect(rule(".assistant-markdown pre")).toContain("overflow-x: auto");
  expect(rule(".assistant-conversation")).toContain("min-width: 0");
  expect(rule(".assistant-page-main")).toContain("min-width: 0");
  expect(rule(".assistant-page-bar")).toContain("min-width: 0");
  expect(rule(".assistant-page-title")).toMatch(/text-overflow: ellipsis;.*white-space: nowrap/);
  // On phones the chat page is one column whose track can shrink below its content.
  expect(css).toContain(".assistant-page { grid-template-columns: minmax(0, 1fr);");
});
