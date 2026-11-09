import { fireEvent, render, screen } from "@testing-library/react";
import { Link, MemoryRouter } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import { CyberMetadata } from "./CyberMetadata";

const state = vi.hoisted(() => ({ data: undefined as object | undefined, isPending: false }));
vi.mock("@/hooks/usePapers", () => ({ usePaper: () => state }));
afterEach(() => { document.head.innerHTML = ""; state.data = undefined; });
const canonical = () => document.querySelector('link[rel="canonical"]')?.getAttribute("href");

it("updates canonical, title and Markdown links when navigating catalog pages", () => {
  render(<MemoryRouter><CyberMetadata /><Link to="/catalog?offset=25&utm_source=test">Catalog</Link></MemoryRouter>);
  expect(document.title).toContain("Security Agent Harnesses");
  fireEvent.click(screen.getByText("Catalog"));
  expect(canonical()).toBe("https://paperswithcode-cyber.com/catalog?offset=25");
  expect(document.title).toContain("Page 2");
  expect(document.querySelector('meta[name="robots"]')).toHaveAttribute("content", "index,follow");
  expect(document.querySelector('link[type="text/markdown"]')).toHaveAttribute("href", "https://paperswithcode-cyber.com/catalog.md?offset=25");
});

it("preserves selected facets and removes stale paper structured data on navigation", () => {
  document.head.innerHTML = '<script type="application/ld+json">{"old":"paper"}</script>';
  state.data = { id: "42", source: "arxiv", arxiv_id: "2610.34435", title: "A security paper", abstract: "Evidence" };
  render(<MemoryRouter initialEntries={["/paper/2610.34435"]}><CyberMetadata /><Link to="/catalog?contribution=harness&offset=25">Filtered</Link><Link to="/developers">Developers</Link></MemoryRouter>);
  expect(canonical()).toContain("/paper/2610.34435");
  fireEvent.click(screen.getByText("Filtered"));
  expect(canonical()).toBe("https://paperswithcode-cyber.com/catalog?contribution=harness&offset=25");
  expect(document.querySelector('meta[name="robots"]')).toHaveAttribute("content", "noindex,follow");
  expect(document.querySelector('script[type="application/ld+json"]')).toBeNull();
  fireEvent.click(screen.getByText("Developers"));
  expect(canonical()).toBeUndefined();
  expect(document.querySelector('link[type="text/markdown"]')).toBeNull();
});
