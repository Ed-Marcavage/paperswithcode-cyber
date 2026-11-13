import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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
      anchor_date: "2026-11-12", window_days: 14, this_week: false, results: [{
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

it("shows industry posts above the paper feed and switches the feed to posts", async () => {
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <MemoryRouter initialEntries={["/"]}><FeedView /></MemoryRouter>
  </QueryClientProvider>);

  expect(await screen.findByRole("heading", { name: "Recent from industry" })).toBeInTheDocument();
  expect(screen.getByText(/The block at the top shows hand-picked industry engineering posts\./)).toBeInTheDocument();
  expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Trending Research");
  expect(screen.getByRole("link", { name: "Highlighted post" })).toHaveAttribute("href", "/paper/9");
  expect(await screen.findByText("Trending paper")).toBeInTheDocument();
  expect(papersApi.list).toHaveBeenCalledWith(expect.objectContaining({ order_by: "trending" }));
  expect(screen.getByRole("button", { name: "papers" })).toHaveAttribute("aria-pressed", "true");

  fireEvent.click(screen.getByRole("button", { name: "posts" }));
  expect(await screen.findByText("Ranked post")).toBeInTheDocument();
  expect(screen.queryByText("Trending paper")).not.toBeInTheDocument();
  await waitFor(() => expect(calls.some(path => path.startsWith("/catalog/trending-posts?") && path.includes("page=1"))).toBe(true));
});
