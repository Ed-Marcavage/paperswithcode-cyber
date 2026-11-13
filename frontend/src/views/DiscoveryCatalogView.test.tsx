import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { expect, it, vi } from "vitest";
import * as request from "@/lib/api/request";
import DiscoveryCatalogView from "./DiscoveryCatalogView";

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
