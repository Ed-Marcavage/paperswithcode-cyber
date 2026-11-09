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
