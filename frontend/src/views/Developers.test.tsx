import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import * as request from "@/lib/api/request";
import { developerParams, developerSort } from "@/lib/api/developers";
import { DevelopersIndex } from "./Developers";

afterEach(() => vi.restoreAllMocks());

const dev = (github_id: number, login: string, agent_work_count: number, repository_count: number,
  owned_stars: number | null = null) => ({
  github_id, login, agent_work_count, repository_count, owned_stars, featured_repo: `${login}/tool`,
});

// Backend order for the default sort: agent-related works first, so a developer with fewer
// tracked repos can lead.
const payload = { count: 2, results: [dev(1, "agentdev", 7, 2), dev(2, "prolific", 1, 9, 40)],
  facet_counts: { topic: {}, target: {}, contribution: {} } };

const Location = () => <output data-testid="location">{useLocation().search}</output>;

function renderView(path = "/developers") {
  const api = vi.spyOn(request, "apiRequest").mockImplementation(async (url: string) =>
    (url.startsWith("/developers/") ? payload : {}) as never);
  const view = render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter initialEntries={[path]}>
        <Routes><Route path="/developers" element={<><DevelopersIndex /><Location /></>} /></Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  const developerCalls = () => api.mock.calls.map(([url]) => url as string).filter(url => url.startsWith("/developers/"));
  const metrics = () => [...view.container.querySelectorAll(".organization-card-metrics")].map(node => node.textContent);
  return { developerCalls, metrics };
}

describe("DevelopersIndex", () => {
  it("defaults to Most agent-related work and shows the ranked count on each card", async () => {
    const { developerCalls, metrics } = renderView();
    await screen.findByRole("heading", { name: "agentdev" });

    expect(screen.getByRole("button", { name: "Most agent-related work" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Most tracked repos" })).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByText("Sorted by papers plus agent-related posts")).toBeInTheDocument();
    // The default sort is the API's default, so the request carries no sort.
    expect(new URLSearchParams(developerCalls()[0].split("?")[1]).has("sort")).toBe(false);
    expect(metrics()).toEqual(["7agent-related works2 tracked repos", "1agent-related work9 tracked repos"]);
  });

  it("keeps Most tracked repos and Most stars reachable, with their old cards", async () => {
    const user = userEvent.setup();
    const { developerCalls, metrics } = renderView();
    await screen.findByRole("heading", { name: "agentdev" });

    await user.click(screen.getByRole("button", { name: "Most tracked repos" }));
    expect(screen.getByTestId("location")).toHaveTextContent("?sort=repos");
    await screen.findByText("Most tracked repos", { selector: ".organizations-section-heading span" });
    expect(developerCalls().at(-1)).toContain("sort=repos");
    expect(metrics()).toEqual(["2tracked repos", "9tracked repos"]);

    await user.click(screen.getByRole("button", { name: "Most stars" }));
    expect(screen.getByTestId("location")).toHaveTextContent("?sort=stars");
    expect(developerCalls().at(-1)).toContain("sort=stars");
    expect(metrics()).toEqual(["—owned repo stars", "40owned repo stars"]);

    await user.click(screen.getByRole("button", { name: "Most agent-related work" }));
    expect(screen.getByTestId("location")).toBeEmptyDOMElement();
  });

  it("says matching when filters narrow the count", async () => {
    const { metrics } = renderView("/developers?topic=penetration-testing");
    await screen.findByRole("heading", { name: "agentdev" });
    expect(metrics()[0]).toBe("7matching agent-related works2 matching repos");
  });
});

describe("developer sort parameters", () => {
  it("treats a missing or unknown sort as the agent-related default and keeps old values", () => {
    expect(developerSort(null)).toBe("agent");
    expect(developerSort("bogus")).toBe("agent");
    expect(developerSort("repos")).toBe("repos");
    expect(developerSort("stars")).toBe("stars");
    expect(new URLSearchParams(developerParams(new URLSearchParams("sort=agent"), 1)).has("sort")).toBe(false);
    expect(new URLSearchParams(developerParams(new URLSearchParams("sort=repos&q=x"), 2)).get("sort")).toBe("repos");
    expect(new URLSearchParams(developerParams(new URLSearchParams("sort=stars"), 1)).get("sort")).toBe("stars");
  });
});
