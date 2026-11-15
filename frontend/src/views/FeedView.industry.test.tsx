import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { catalogApi } from "@/lib/api/catalog";
import { papersApi } from "@/lib/api/papers";
import * as request from "@/lib/api/request";
import FeedView from "@/views/FeedView";

vi.mock("@/lib/authContext", () => ({ useAuth: () => null, useOptionalAuth: () => null }));
vi.mock("@/hooks/useIntersectionObserver", () => ({
  useIntersectionObserver: () => ({ targetRef: { current: null }, isIntersecting: false }),
}));

const card = (id: number, title: string, catalogKind: string) => ({
  id: String(id), arxiv_id: null, title, abstract: "", authors: [], published: "2026-11-10",
  catalog_kind: catalogKind, source_url: "https://example.com/" + id,
});
const calls: string[] = [];

beforeEach(() => {
  calls.length = 0;
  vi.stubEnv("VITE_LOCAL_CATALOG", "true");
  vi.stubEnv("VITE_CHAT_ENABLED", "false");
  vi.spyOn(catalogApi, "topTasks").mockResolvedValue([]);
  vi.spyOn(catalogApi, "trendingTasks").mockResolvedValue({ results: [] } as never);
  vi.spyOn(papersApi, "list").mockResolvedValue({
    count: 1, next_page: null, previous_page: null, results: [card(1, "Trending paper", "paper")],
  } as never);
  vi.spyOn(request, "apiRequest").mockImplementation(async (path: string) => {
    calls.push(path);
    if (path.startsWith("/catalog/trending-posts/highlights")) return {
      anchor_date: "2026-11-12", window_days: null, this_week: false, pinned: 1, heading: "Editor's picks", results: [{
        paper_id: "9", reference: "9", title: "Highlighted post", source_url: "https://wiz.io/x", artifact_url: null,
        has_text: true, date_published: "2026-11-10", facets: { kind: ["post"] },
        post: { tier: "featured", post_type: "other", tldr: "Summary.", subtopics: [], authors: [], technical_depth: 2,
          originality: 2, agent_relevance: 3, reports_benchmark_results: false, agent_harness_engineering: false, entities: [] },
      }],
    };
    if (path.startsWith("/catalog/trending-posts")) return {
      count: 1, next_page: null, previous_page: null, results: [card(2, "Ranked post", "post")],
    };
    throw new Error("unexpected " + path);
  });
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

const renderFeed = (entry: string) => render(
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <MemoryRouter initialEntries={[entry]}><FeedView /></MemoryRouter>
  </QueryClientProvider>,
);

it("shows the Editor's picks block above the feed, lists posts by default and switches to papers", async () => {
  renderFeed("/");

  const picks = await screen.findByRole("heading", { name: "Editor's picks" });
  expect(screen.getByText(/Editor's picks are three hand-picked industry posts; the feed below ranks other industry posts and research papers\./)).toBeInTheDocument();
  // The block sits above the feed's controls.
  expect(picks.compareDocumentPosition(screen.getByRole("button", { name: "posts" })) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Trending Research");
  expect(screen.getByRole("link", { name: "Highlighted post" })).toHaveAttribute("href", "/paper/9");
  expect(await screen.findByText("Ranked post")).toBeInTheDocument();
  expect(screen.getByText(/featured posts about AI agents, ranked by review scores/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "posts" })).toHaveAttribute("aria-pressed", "true");
  await waitFor(() => expect(calls.some(path => path.startsWith("/catalog/trending-posts?") && path.includes("page=1"))).toBe(true));
  expect(papersApi.list).not.toHaveBeenCalled();

  fireEvent.click(screen.getByRole("button", { name: "papers" }));
  expect(await screen.findByText("Trending paper")).toBeInTheDocument();
  expect(screen.queryByText("Ranked post")).not.toBeInTheDocument();
  expect(papersApi.list).toHaveBeenCalledWith(expect.objectContaining({ order_by: "trending" }));
  expect(screen.getByRole("button", { name: "papers" })).toHaveAttribute("aria-pressed", "true");

  fireEvent.click(screen.getByRole("button", { name: "posts" }));
  expect(await screen.findByText("Ranked post")).toBeInTheDocument();
});

it("keeps the kind URL parameter working", async () => {
  renderFeed("/?kind=paper");
  expect(await screen.findByText("Trending paper")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "papers" })).toHaveAttribute("aria-pressed", "true");
  cleanup();

  renderFeed("/?kind=post");
  expect(await screen.findByText("Ranked post")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "posts" })).toHaveAttribute("aria-pressed", "true");
});

it("explains an empty Papers view instead of showing a blank area", async () => {
  vi.mocked(papersApi.list).mockResolvedValue({ count: 0, next_page: null, previous_page: null, results: [] } as never);
  renderFeed("/?kind=paper");
  expect(await screen.findByText(/No trending papers right now: paper ranking needs GitHub star counts from the last 24 hours\./)).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Browse all papers in the catalog" })).toHaveAttribute("href", "/catalog?kind=paper");
  cleanup();

  renderFeed("/?kind=paper&start_date=2026-11-01&end_date=2026-11-07");
  expect(await screen.findByText("No papers in this window.")).toBeInTheDocument();
});
