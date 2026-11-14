import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { expect, it } from "vitest";

import type { Paper, Repository } from "@/lib/api/papers.types";
import { PaperResourceSidebar } from "./PaperResourceSidebar";

const repository = (overrides: Partial<Repository>): Repository => ({
  id: "1", paper_id: "4531", url: "https://github.com/NVIDIA/skillevaluator", owner: "NVIDIA", name: "skillevaluator",
  num_stars: 0, is_official: false, source: "cyberintel-local", num_stars_updated_at: null, ...overrides,
});

const renderSidebar = (paper: Partial<Paper>) => render(
  <MemoryRouter>
    <PaperResourceSidebar
      allHfArtifactUrls={{ models: [], datasets: [], spaces: [] }}
      citationCopied={false}
      citationDisplay=""
      hfArtifactViewer={{ isLoading: false, paperHref: null, rows: [], footer: null }}
      onCopyCitation={() => {}}
      onEditHfArtifacts={() => {}}
      onEditRepositories={() => {}}
      onEditXThreads={() => {}}
      paper={{ id: "4531", title: "A post", authors: [], ...paper } as unknown as Paper}
      relatedIsLoading={false}
      relatedPapers={[]}
      user={null}
    />
  </MemoryRouter>,
);

it("groups a post's repositories by role, original first, with evidence and no unobserved stars", () => {
  renderSidebar({
    catalog_kind: "post",
    repositories: [
      repository({ id: "4", url: "https://github.com/harbor-framework/harbor", owner: "harbor-framework", name: "harbor",
        role: "dependency", evidence: "Harbor runs the isolated agent trials." }),
      repository({ id: "1", role: "original", is_official: true, num_stars: 1120, num_stars_updated_at: "2026-11-13T23:34:49Z",
        evidence: "The authors' released implementation." }),
    ],
  });
  const groups = screen.getAllByRole("heading", { level: 3 }).map((heading) => heading.textContent);
  expect(groups).toEqual(["Code released with this post", "Depends on"]);

  const original = screen.getByRole("region", { name: "Code released with this post" });
  expect(within(original).getByText("★ 1.1k")).toBeInTheDocument();
  expect(within(original).getByText("The authors' released implementation.")).toBeInTheDocument();
  expect(within(original).getByRole("link", { name: /Referenced by/ })).toHaveAttribute("href", "/repos/NVIDIA/skillevaluator");

  const dependency = screen.getByRole("region", { name: "Depends on" });
  expect(within(dependency).getByText("Harbor runs the isolated agent trials.")).toBeInTheDocument();
  expect(within(dependency).queryByText(/★/)).not.toBeInTheDocument();
});

it("says so when a post links no repositories", () => {
  renderSidebar({ catalog_kind: "post", repositories: [] });
  expect(screen.getByText("No GitHub repositories linked to this post.")).toBeInTheDocument();
});

it("keeps the paper sidebar's flat list", () => {
  renderSidebar({ catalog_kind: "paper", repositories: [repository({ is_official: true, num_stars: 0 })] });
  expect(screen.queryByRole("heading", { level: 3 })).not.toBeInTheDocument();
  expect(screen.getByText("· Official")).toBeInTheDocument();
  expect(screen.getByText("★ 0")).toBeInTheDocument();
});
