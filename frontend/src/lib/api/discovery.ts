import { queryOptions } from "@tanstack/react-query";
import type { CatalogPost, Paper } from "./papers.types";
import type { PaginatedResponse } from "./shared.types";
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
  /** ISO publication date; sent by the Trending industry highlights. */
  date_published?: string | null;
  /** Company name (curated name, else the backend's host map, else the host); sent by the highlights. */
  publisher?: string | null;
}
/** Industry posts for the top of Trending (backend `trending_posts.industry_block`). */
export interface IndustryHighlights {
  /** Newest reviewed post's date; windows count back from it. */
  anchor_date: string | null;
  /** 14, or 30 when 14 days held too few posts. */
  window_days: number;
  /** No pinned posts, and at least 3 of the results are from the 7 days before the anchor. */
  this_week: boolean;
  /** How many results are owner-pinned (curated manifest `pinned`); they come first. */
  pinned?: number;
  /** Heading chosen by the backend; it only makes a date claim when nothing is pinned. */
  heading?: string;
  results: DiscoveryWork[];
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
export const industryHighlightsQuery = queryOptions({
  queryKey: ["discovery", "industry-highlights"],
  queryFn: () => apiRequest<IndustryHighlights>("/catalog/trending-posts/highlights"),
  staleTime: 300_000,
});
/** Featured industry posts ranked for Trending's "posts" view, as paper records for PaperCard. */
export function trendingPosts(params: {
  page: number; page_size: number; include_resources?: boolean; start_date?: string; end_date?: string;
}): Promise<PaginatedResponse<Paper>> {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) if (value !== undefined && value !== "") query.set(key, String(value));
  return apiRequest<PaginatedResponse<Paper>>("/catalog/trending-posts?" + query);
}
export function discoveryPaperQuery(id: string) {
  return queryOptions({
    queryKey: ["discovery", "paper", id],
    queryFn: () => apiRequest<DiscoveryWork>("/catalog/papers/" + encodeURIComponent(id)),
  });
}
