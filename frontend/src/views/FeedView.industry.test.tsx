import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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

const card = (id: number, title: string, catalogKind: string, post?: Record<string, unknown>) => ({
  id: String(id), arxiv_id: null, title, abstract: "", authors: [], published: "2026-11-10",
  catalog_kind: catalogKind, source_url: "https://example.com/" + id,
  ...(post && { catalog_post: {
    tier: "featured", post_type: "other", tldr: "Summary.", subtopics: [], authors: [], technical_depth: 2,
    originality: 2, agent_relevance: 3, reports_benchmark_results: false, agent_harness_engineering: false,
    entities: [], ...post,
  } }),
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
    if (path.startsWith("/catalog/trending-posts?")) return {
      count: 3, next_page: null, previous_page: null, results: [
        card(9, "Pinned post", "post", { curated: true, curated_pin: 1 }),
        card(2, "Ranked post", "post", {}),
        card(3, "Curated post", "post", { curated: true }),
      ],
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

it("lists posts by default, pinned rows first with an Editor's pick badge, and switches to papers", async () => {
  renderFeed("/");

  expect(await screen.findByText("Ranked post")).toBeInTheDocument();
  expect(screen.getByText(/The posts list starts with the editor's picks, then ranks other posts about AI agents\./)).toBeInTheDocument();
  expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Trending Research");
  // One list: no separate block of picks above the feed, and no call for one.
  expect(screen.queryByRole("heading", { name: /from industry/i })).not.toBeInTheDocument();
  expect(screen.queryByRole("link", { name: /See all industry posts/ })).not.toBeInTheDocument();
  expect(calls.some(path => path.startsWith("/catalog/trending-posts/highlights"))).toBe(false);
  const titles = screen.getAllByRole("heading", { level: 3 }).map(heading => heading.textContent);
  expect(titles).toEqual(["Pinned post", "Ranked post", "Curated post"]);
  const cardOf = (title: string) => screen.getByText(title).closest("article")!;
  expect(within(cardOf("Pinned post")).getByText("Editor's pick")).toBeInTheDocument();
  expect(within(cardOf("Ranked post")).queryByText("Editor's pick")).not.toBeInTheDocument();
  expect(within(cardOf("Curated post")).queryByText("Editor's pick")).not.toBeInTheDocument();
  expect(screen.getAllByText("Editor's pick")).toHaveLength(1);
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
