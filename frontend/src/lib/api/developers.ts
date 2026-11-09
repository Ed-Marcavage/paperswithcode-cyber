import { apiRequest, apiRequestOrNull } from "./request";

interface Developer {
  github_id: number;
  login: string;
}

interface DeveloperCard extends Developer {
  repository_count: number;
  featured_repo: string;
  owned_stars: number | null;
}

interface DeveloperProfile extends Developer {
  repositories: {
    github_repo_id: number;
    full_name: string;
    owns: boolean;
    commits: number;
  }[];
}

export const developerPageSize = 24;

export const developerAxes = ["topic", "target", "contribution"] as const;
type DeveloperAxis = typeof developerAxes[number];

export function developerParams(params: URLSearchParams, page: number) {
  const result = new URLSearchParams({
    limit: String(developerPageSize), offset: String((page - 1) * developerPageSize), include_facet_counts: "true",
  });
  for (const key of ["q", "repository", ...developerAxes]) {
    const value = params.get(key);
    if (value) result.set(key, value);
  }
  if (params.get("sort") === "stars") result.set("sort", "stars");
  return result.toString();
}

export function getDevelopers(query: string) {
  return apiRequest<{ count: number; results: DeveloperCard[]; facet_counts: Record<DeveloperAxis, Record<string, number>> }>(
    `/developers/?${query}`,
  );
}

export function getDeveloper(id: string) {
  return apiRequestOrNull<DeveloperProfile>(`/developers/${encodeURIComponent(id)}`);
}
