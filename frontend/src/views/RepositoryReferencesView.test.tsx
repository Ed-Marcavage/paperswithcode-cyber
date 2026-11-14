import { render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";

import * as request from "@/lib/api/request";
import RepositoryReferencesView from "./RepositoryReferencesView";

afterEach(() => vi.restoreAllMocks());

const renderView = (path: string) => render(
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <MemoryRouter initialEntries={[path]}>
      <Routes><Route path="/repos/:owner/:name" element={<RepositoryReferencesView />} /></Routes>
    </MemoryRouter>
  </QueryClientProvider>,
);

it("lists the papers and posts referencing a repository, by role", async () => {
  const api = vi.spyOn(request, "apiRequest").mockResolvedValue({
    repository: { id: "969", url: "https://github.com/rapid7/metasploit-framework", owner: "rapid7",
      name: "metasploit-framework", num_stars: 39576, num_stars_updated_at: "2026-11-13T23:35:40Z" },
    total: 2,
    references: {
      original: [{ paper_id: "4010", reference: "4010", title: "BeyondTrust file upload to RCE", kind: "post",
        date_published: "2026-10-30", source_url: "https://www.rapid7.com/blog/post/x", is_official: true,
        evidence: "Links the Metasploit module for the chain.", link_url: null, publisher: "Rapid7" }],
      target: [{ paper_id: "12", reference: "2601.00001", title: "Exploit agents", kind: "paper",
        date_published: "2026-01-02", source_url: "https://arxiv.org/abs/2601.00001", is_official: false,
        evidence: null, link_url: null }],
    },
  });
  renderView("/repos/rapid7/metasploit-framework");

  expect(await screen.findByRole("heading", { level: 2, name: "Referenced by" })).toBeInTheDocument();
  expect(screen.getByRole("heading", { level: 1, name: "rapid7/metasploit-framework" })).toBeInTheDocument();
  expect(api).toHaveBeenCalledWith("/catalog/repositories/rapid7/metasploit-framework");
  expect(screen.getByText(/39.6K stars/i)).toBeInTheDocument();

  const released = screen.getByRole("region", { name: "Released by" });
  expect(within(released).getByRole("link", { name: "BeyondTrust file upload to RCE" })).toHaveAttribute("href", "/paper/4010");
  expect(within(released).getByText("Industry post · Rapid7 · Oct 30, 2026")).toBeInTheDocument();
  expect(within(released).getByText("Links the Metasploit module for the chain.")).toBeInTheDocument();
  expect(within(screen.getByRole("region", { name: "Targeted or tested by" })).getByText("Paper · Jan 2, 2026")).toBeInTheDocument();
});
