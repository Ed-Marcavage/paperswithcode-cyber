import { render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import * as request from "@/lib/api/request";
import * as analytics from "@/lib/catalogAnalytics";
import { industryHeading } from "@/lib/industryPost";
import { TrendingIndustry } from "./TrendingIndustry";

const post = {
  tier: "featured", post_type: "benchmark-or-evaluation", tldr: "One-sentence summary.", subtopics: [], authors: [],
  technical_depth: 3, originality: 3, agent_relevance: 4, reports_benchmark_results: true,
  agent_harness_engineering: false, entities: [],
};
const highlights = (thisWeek: boolean) => ({
  anchor_date: "2026-11-12", window_days: 14, this_week: thisWeek, results: [
    { paper_id: "1012", reference: "1012", title: "How to Evaluate AI Agent Cybersecurity Capabilities",
      source_url: "https://www.wiz.io/blog/cyber-model-arena-ai-benchmark", artifact_url: null, has_text: true,
      date_published: "2026-11-10", facets: { kind: ["post"] },
      post: { ...post, curated: true, curated_company: "Wiz", curated_title: "Evaluating AI agent cyber capabilities" } },
    { paper_id: "3961", reference: "3961", title: "Help defend against memory poisoning",
      source_url: "https://aws.amazon.com/blogs/security/help-defend", artifact_url: null, has_text: true,
      date_published: "2026-11-09", facets: { kind: ["post"] }, post: { ...post, post_type: "engineering-practice" } },
  ],
});

const renderBlock = () => render(
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <MemoryRouter><TrendingIndustry /></MemoryRouter>
  </QueryClientProvider>,
);

afterEach(() => vi.restoreAllMocks());

it("names the block by how recent its posts are", () => {
  expect(industryHeading({ this_week: true })).toBe("From industry this week");
  expect(industryHeading({ this_week: false })).toBe("Recent from industry");
});

it("shows compact post cards linking to detail pages, with the editor's company and title for curated posts", async () => {
  vi.spyOn(request, "apiRequest").mockResolvedValue(highlights(true));
  const handlers = vi.spyOn(analytics, "paperLinkHandlers");
  renderBlock();
  expect(await screen.findByRole("heading", { name: "From industry this week" })).toBeInTheDocument();
  const curated = screen.getByRole("link", { name: "Evaluating AI agent cyber capabilities" });
  expect(curated).toHaveAttribute("href", "/paper/1012");
  const card = curated.closest("article")!;
  expect(within(card).getByText("Wiz · Benchmark or evaluation · Nov 10, 2026")).toBeInTheDocument();
  expect(within(card).getByText("One-sentence summary.")).toBeInTheDocument();
  expect(within(card).getByText("Editor's pick")).toBeInTheDocument();
  expect(within(card).getByRole("link", { name: "Featured" })).toBeInTheDocument();

  const other = screen.getByRole("link", { name: "Help defend against memory poisoning" }).closest("article")!;
  expect(within(other).getByText("aws.amazon.com · Engineering practice · Nov 9, 2026")).toBeInTheDocument();
  expect(within(other).queryByText("Editor's pick")).not.toBeInTheDocument();

  expect(screen.getByRole("link", { name: "See all industry posts →" })).toHaveAttribute("href", "/catalog?kind=post&order=featured");
  expect(handlers).toHaveBeenCalledWith("1012", "How to Evaluate AI Agent Cybersecurity Capabilities", "title",
    "trending_industry", { kind: ["post"] });
});

it("falls back to the plain heading", async () => {
  vi.spyOn(request, "apiRequest").mockResolvedValue(highlights(false));
  renderBlock();
  expect(await screen.findByRole("heading", { name: "Recent from industry" })).toBeInTheDocument();
});

it("renders nothing when there are no posts", async () => {
  const api = vi.spyOn(request, "apiRequest").mockResolvedValue({ ...highlights(true), results: [] });
  const { container } = renderBlock();
  await vi.waitFor(() => expect(api).toHaveBeenCalled());
  expect(container).toBeEmptyDOMElement();
});
