import { fireEvent, render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import * as request from "@/lib/api/request";
import { DiscoveryPaper } from "./DiscoveryPaper";

const post = {
  tier: "featured", post_type: "benchmark-or-evaluation", tldr: "Wiz outlines principles.", subtopics: [], authors: [],
  technical_depth: 3, originality: 3, agent_relevance: 4, reports_benchmark_results: true,
  agent_harness_engineering: true, entities: [], caveat: "Vendor-run leaderboard.",
  curated_title: "How to Evaluate AI Agent Cybersecurity Capabilities",
};
const work = (kind: string, extra = {}) => ({
  paper_id: "1012", reference: "1012", title: "How to Evaluate AI Agent Cybersecurity Capabilities",
  facets: { kind: [kind], topic: ["penetration-testing"] }, source_url: "https://www.wiz.io/blog/cyber-model-arena-ai-benchmark",
  artifact_url: null, has_text: false, post: kind === "post" ? post : null, ...extra,
});

function renderDetails(data: object, thumbnailUrl: string | null) {
  vi.spyOn(request, "apiRequest").mockImplementation(async (path: string) =>
    path.startsWith("/catalog/filters") ? {} : data);
  return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <MemoryRouter><DiscoveryPaper paperId="1012" title="How to Evaluate AI Agent Cybersecurity Capabilities" thumbnailUrl={thumbnailUrl} /></MemoryRouter>
  </QueryClientProvider>);
}

afterEach(() => vi.restoreAllMocks());

it("shows a post's screenshot beside the rows, opening the original post in a new tab, with the link under it", async () => {
  const { container } = renderDetails(work("post"), "/api/v1/catalog/papers/1012/preview/abc.jpg");
  const shot = await screen.findByRole("link", { name: "Open the original post: How to Evaluate AI Agent Cybersecurity Capabilities" });
  expect(shot).toHaveAttribute("href", "https://www.wiz.io/blog/cyber-model-arena-ai-benchmark");
  expect(shot).toHaveAttribute("target", "_blank");
  expect(shot).toHaveAttribute("rel", "noopener noreferrer");
  expect(shot.querySelector("img")).toHaveAttribute("src", "/api/v1/catalog/papers/1012/preview/abc.jpg");
  const column = shot.closest("aside")!;
  const read = within(column).getByRole("link", { name: "Read original post ↗" });
  // The link sits directly under the image, and only there.
  expect(shot.nextElementSibling).toBe(read);
  expect(screen.getAllByRole("link", { name: "Read original post ↗" })).toHaveLength(1);
  expect(container.querySelector(".discovery-paper")).toHaveClass("has-preview");
  expect(container.querySelector(".discovery-paper-rows")).toHaveTextContent("Vendor-run leaderboard.");
});

it("falls back to one column with the link under the rows when the post has no image or it fails", async () => {
  const { container, unmount } = renderDetails(work("post"), null);
  const read = await screen.findByRole("link", { name: "Read original post ↗" });
  expect(read.closest(".discovery-resources")).not.toBeNull();
  expect(container.querySelector("aside, img")).toBeNull();
  expect(container.querySelector(".discovery-paper")).not.toHaveClass("has-preview");
  unmount();

  const failed = renderDetails(work("post"), "/broken.jpg");
  fireEvent.error((await screen.findByRole("link", { name: /Open the original post/ })).querySelector("img")!);
  expect(failed.container.querySelector("aside, img")).toBeNull();
  expect(screen.getByRole("link", { name: "Read original post ↗" }).closest(".discovery-resources")).not.toBeNull();
});

it("leaves research papers as they were: no screenshot column, their own source link", async () => {
  const { container } = renderDetails(work("paper", { post: null }), "/api/v1/catalog/papers/975/preview/def.jpg");
  expect(await screen.findByRole("link", { name: "Read at source ↗" })).toBeInTheDocument();
  expect(screen.getByText(/No cached text\./)).toBeInTheDocument();
  expect(container.querySelector("aside, img")).toBeNull();
});
