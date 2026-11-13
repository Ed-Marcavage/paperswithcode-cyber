import { queryOptions } from "@tanstack/react-query";
import type { CatalogPost } from "./papers.types";
import { apiRequest } from "./request";

export const axes = {
  topic: "Topic", target: "Target", contribution: "Contribution", kind: "Source type", year: "Year",
} as const;
export type Axis = keyof typeof axes;
export type Terms = Partial<Record<Axis, Record<string, string>>>;
export interface DiscoveryWork {
  paper_id: string;
  reference: string;
  title: string;
  facets: Partial<Record<Axis, string[]>>;
  source_url: string;
  artifact_url: string | null;
  has_text: boolean;
  /** Reviewed industry-post fields; null for papers and repositories. */
  post?: CatalogPost | null;
}
export const filtersQuery = queryOptions({
  queryKey: ["discovery", "filters"],
  queryFn: () => apiRequest<Terms>("/catalog/filters"),
  staleTime: 300_000,
});
export function browseQuery(params: URLSearchParams) {
  const query = params.toString();
  return queryOptions({
    queryKey: ["discovery", "browse", query],
    queryFn: () => apiRequest<{
      total: number;
      results: DiscoveryWork[];
      facet_counts?: Record<Axis, Record<string, number>>;
    }>("/catalog/papers?" + query),
  });
}
export function discoveryPaperQuery(id: string) {
  return queryOptions({
    queryKey: ["discovery", "paper", id],
    queryFn: () => apiRequest<DiscoveryWork>("/catalog/papers/" + encodeURIComponent(id)),
  });
}
