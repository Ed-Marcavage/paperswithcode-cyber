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
  /** ISO publication date; sent by the Trending Editor's picks. */
  date_published?: string | null;
  /** Industry posts: company name (picks: curated name first; then the publisher organization, else the host). */
  publisher?: string | null;
  /** Preview image address (the post's screenshot or the paper's thumbnail); sent by the Editor's picks. */
  thumbnail_url?: string | null;
  /** The editor's pin number, for any kind of work (a paper or an unreviewed post has no `post`). */
  curated_pin?: number | null;
  /** Editor's picks only: catalog kind (`post`, `paper`, ...). */
  kind?: string | null;
  /** Editor's picks only: author names in order; papers show them where posts show the publisher. */
  authors?: string[];
  /** Editor's picks only: the review's one-sentence summary, else the paper's abstract. */
  summary?: string | null;
}
/** Trending's Editor's picks block (backend `trending_posts.industry_block`): the first pins, in pin order.
 * A pick is any catalog work: a reviewed post, a post without a review, or a research paper. */
export interface IndustryHighlights {
  /** Newest reviewed post's date. */
  anchor_date: string | null;
  /** Kept for the route's earlier shape; the picks do not depend on a date window. */
  window_days: number | null;
  this_week: boolean;
  /** How many results are owner-pinned (curated manifest `pinned`); all of them are. */
  pinned?: number;
  /** "Editor's picks". */
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
/** One catalog work citing a repository (backend `discovery_catalog.repository_references`). */
export interface RepositoryReference {
  paper_id: string;
  reference: string;
  title: string;
  kind: string | null;
  date_published: string | null;
  source_url: string;
  is_official: boolean;
  evidence: string | null;
  link_url: string | null;
  /** Industry posts only: the publisher organization's name, else the host. */
  publisher?: string | null;
}
export interface RepositoryReferences {
  repository: {
    id: string; url: string; owner: string; name: string;
    num_stars: number; num_stars_updated_at: string | null;
  };
  total: number;
  /** Works grouped by role (original, target, supporting, dependency, unspecified), newest first. */
  references: Record<string, RepositoryReference[]>;
}
export function repositoryReferencesQuery(owner: string, name: string) {
  return queryOptions({
    queryKey: ["discovery", "repository-references", owner.toLowerCase(), name.toLowerCase()],
    queryFn: () => apiRequest<RepositoryReferences>(
      `/catalog/repositories/${encodeURIComponent(owner)}/${encodeURIComponent(name)}`),
    staleTime: 300_000,
  });
}
