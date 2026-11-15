import { fireEvent, render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import * as request from "@/lib/api/request";
import * as analytics from "@/lib/catalogAnalytics";
import { TrendingIndustry } from "./TrendingIndustry";

const post = {
  tier: "featured", post_type: "benchmark-or-evaluation", tldr: "One-sentence summary.", subtopics: [], authors: [],
  technical_depth: 3, originality: 3, agent_relevance: 4, reports_benchmark_results: true,
  agent_harness_engineering: false, entities: [],
};
const picks = () => ({
  anchor_date: "2026-11-13", window_days: null, this_week: false, pinned: 3, heading: "Editor's picks", results: [
    { paper_id: "2115", reference: "2115", title: "ARTEX and Beyond: AI-Enabled Penetration Testing Platforms",
      source_url: "https://blog.talosintelligence.com/artex-and-beyond/", artifact_url: null, has_text: true,
      date_published: "2026-11-13", facets: { kind: ["post"] }, publisher: "Cisco Talos",
      thumbnail_url: "/api/v1/catalog/papers/2115/preview/abc.jpg",
      post: { ...post, post_type: "malware-or-threat-intel", curated: true, curated_pin: 1, curated_company: "Cisco Talos",
        curated_title: "ARTEX and Beyond, AI-Enabled Penetration Testing Platforms" } },
    { paper_id: "2114", reference: "2114", title: "Threat actors running cybercrime campaigns with ARTEX AI agents",
      source_url: "https://aws.amazon.com/blogs/security/x", artifact_url: null, has_text: true,
      date_published: "2026-11-13", facets: { kind: ["post"] }, publisher: undefined, thumbnail_url: null,
      post: { ...post, curated: true, curated_pin: 2 } },
    { paper_id: "2116", reference: "2116", title: "Cyber Chaos Monkey",
      source_url: "https://shopify.engineering/cyber-chaos-monkey", artifact_url: null, has_text: true,
      date_published: "2026-11-12", facets: { kind: ["post"] }, publisher: "Shopify",
      thumbnail_url: "/api/v1/catalog/papers/2116/preview/def.jpg",
      post: { ...post, post_type: "engineering-practice", curated: true, curated_pin: 3 } },
  ],
});

const renderBlock = () => render(
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <MemoryRouter><TrendingIndustry /></MemoryRouter>
  </QueryClientProvider>,
);

afterEach(() => vi.restoreAllMocks());

it("shows one row of the three picks under the Editor's picks heading, in pin order", async () => {
  const api = vi.spyOn(request, "apiRequest").mockResolvedValue(picks());
  renderBlock();
  expect(await screen.findByRole("heading", { name: "Editor's picks" })).toBeInTheDocument();
  expect(api).toHaveBeenCalledWith("/catalog/trending-posts/highlights");
  const titles = screen.getAllByRole("heading", { level: 3 }).map(heading => heading.textContent);
  expect(titles).toEqual([
    "ARTEX and Beyond, AI-Enabled Penetration Testing Platforms",
    "Threat actors running cybercrime campaigns with ARTEX AI agents",
    "Cyber Chaos Monkey",
  ]);
  expect(screen.getByRole("link", { name: "All industry posts →" })).toHaveAttribute("href", "/catalog?kind=post&order=featured");
});

it("links each card to the post page with the editor's title, company and the post's date", async () => {
  vi.spyOn(request, "apiRequest").mockResolvedValue(picks());
  const handlers = vi.spyOn(analytics, "paperLinkHandlers");
  renderBlock();
  const talos = await screen.findByRole("link", { name: "ARTEX and Beyond, AI-Enabled Penetration Testing Platforms" });
  expect(talos).toHaveAttribute("href", "/paper/2115");
  const card = talos.closest("article")!;
  expect(within(card).getByText("Cisco Talos · Malware or threat intel · Nov 13, 2026")).toBeInTheDocument();
  expect(within(card).getByText("One-sentence summary.")).toBeInTheDocument();
  // Without a publisher or curated company the host names the source.
  const aws = screen.getByRole("link", { name: /cybercrime campaigns/ }).closest("article")!;
  expect(within(aws).getByText("aws.amazon.com · Benchmark or evaluation · Nov 13, 2026")).toBeInTheDocument();
  expect(handlers).toHaveBeenCalledWith("2115", "ARTEX and Beyond: AI-Enabled Penetration Testing Platforms", "title",
    "trending_industry", { kind: ["post"] });
});

it("shows a post's preview image, and no image box when it has none or the image fails", async () => {
  vi.spyOn(request, "apiRequest").mockResolvedValue(picks());
  const { container } = renderBlock();
  await screen.findByRole("heading", { name: "Editor's picks" });
  const cards = container.querySelectorAll("article");
  const talosImage = cards[0].querySelector("img")!;
  expect(talosImage).toHaveAttribute("src", "/api/v1/catalog/papers/2115/preview/abc.jpg");
  expect(talosImage).toHaveAttribute("alt", "");
  expect(cards[1].querySelector(".industry-card-thumb")).toBeNull();
  fireEvent.error(cards[2].querySelector("img")!);
  expect(cards[2].querySelector(".industry-card-thumb")).toBeNull();
});

it("renders nothing when nothing is pinned", async () => {
  const api = vi.spyOn(request, "apiRequest").mockResolvedValue({ ...picks(), pinned: 0, results: [] });
  const { container } = renderBlock();
  await vi.waitFor(() => expect(api).toHaveBeenCalled());
  expect(container).toBeEmptyDOMElement();
});
