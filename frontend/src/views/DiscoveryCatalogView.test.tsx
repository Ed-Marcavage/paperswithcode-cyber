import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import * as request from "@/lib/api/request";
import DiscoveryCatalogView from "./DiscoveryCatalogView";

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllEnvs(); localStorage.clear(); });
function Search() { return <output data-testid="search">{useLocation().search}</output>; }
function catalogApi(total = 1763) {
  vi.spyOn(request, "apiRequest").mockImplementation(async (path: string) => path === "/catalog/filters"
    ? { kind: { post: "Engineering post", paper: "Research paper" }, target: { "ai-systems": "AI systems" } }
    : { total, results: [{ paper_id: "1", reference: "1", title: "A work", facets: {} }] });
}

it("offers crawlable page links that preserve filters and navigate through React", async () => {
  vi.spyOn(request, "apiRequest").mockImplementation(async (path: string) => path === "/catalog/filters"
    ? { contribution: { harness: "Agent harness" } }
    : { total: 76, results: [{ paper_id: "42", reference: "42", title: "Security paper", facets: {} }] });
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <MemoryRouter initialEntries={["/catalog?contribution=harness&offset=25"]}><DiscoveryCatalogView /></MemoryRouter>
  </QueryClientProvider>);
  const next = await screen.findByRole("link", { name: "Next" });
  expect(next).toHaveAttribute("href", "/catalog?contribution=harness&offset=50");
  expect(screen.getByRole("link", { name: "Previous" })).toHaveAttribute("href", "/catalog?contribution=harness");
  fireEvent.click(next);
  await waitFor(() => expect(screen.getByRole("link", { name: "Previous" })).toHaveAttribute("href", "/catalog?contribution=harness&offset=25"));
  vi.restoreAllMocks();
});

it("shows post extras and post-only controls when browsing posts", async () => {
  const calls: string[] = [];
  vi.spyOn(request, "apiRequest").mockImplementation(async (path: string) => {
    calls.push(path);
    return path === "/catalog/filters" ? { kind: { post: "Post" } } : { total: 1, results: [{
      paper_id: "7", reference: "7", title: "Featured post", source_url: "https://www.wiz.io/blog/x",
      facets: { kind: ["post"], year: ["2026"] },
      post: { tier: "featured", post_type: "detection-engineering", tldr: "A short summary.", subtopics: [], authors: [],
        technical_depth: 2, originality: 2, agent_relevance: 1, reports_benchmark_results: false,
        agent_harness_engineering: false, entities: [] },
    }] };
  });
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <MemoryRouter initialEntries={["/catalog?kind=post&order=featured&post_type=detection-engineering"]}><DiscoveryCatalogView /></MemoryRouter>
  </QueryClientProvider>);
  expect(await screen.findByText("A short summary.")).toBeInTheDocument();
  expect(screen.getByText("Detection engineering · wiz.io · 2026")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Featured" })).toBeInTheDocument();
  expect(screen.getByLabelText("Order")).toHaveValue("featured");
  expect(calls.some(path => path.includes("order=featured") && path.includes("post_type=detection-engineering"))).toBe(true);
  vi.restoreAllMocks();
});

it("puts filters in an accessible sheet with removable chips, keeping the URL parameters", async () => {
  catalogApi(218);
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <MemoryRouter initialEntries={["/catalog?kind=post&target=ai-systems"]}><DiscoveryCatalogView /><Search /></MemoryRouter>
  </QueryClientProvider>);
  expect(await screen.findByText("218 results · Showing 1–1")).toBeInTheDocument();
  const trigger = screen.getByRole("button", { name: /Filters/ });
  expect(trigger).toHaveTextContent("2");
  const chips = screen.getByRole("list", { name: "Active filters" });
  expect(within(chips).getByText("AI systems")).toBeInTheDocument();
  fireEvent.click(within(chips).getByRole("button", { name: "Remove filter Target: AI systems" }));
  expect(screen.getByTestId("search")).toHaveTextContent("?kind=post");
  fireEvent.click(trigger);
  const sheet = await screen.findByRole("dialog", { name: "Filters" });
  expect(within(sheet).getByLabelText("Source type")).toHaveValue("post");
  expect(await within(sheet).findByRole("button", { name: "Show 218 results" })).toBeInTheDocument();
  fireEvent.change(within(sheet).getByLabelText("Target"), { target: { value: "ai-systems" } });
  expect(screen.getByTestId("search")).toHaveTextContent("?kind=post&target=ai-systems");
  fireEvent.keyDown(sheet, { key: "Escape" });
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  expect(trigger).toHaveFocus();
  fireEvent.click(trigger);
  fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Clear all" }));
  expect(screen.getByTestId("search")).toBeEmptyDOMElement();
});

