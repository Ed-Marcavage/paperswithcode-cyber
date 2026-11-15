/** Display helpers for reviewed industry posts (catalog kind `post`). */

/** Post type slugs from the industry-intake review, in the review's order. */
export const POST_TYPE_LABELS: Record<string, string> = {
  "vulnerability-writeup": "Vulnerability write-up",
  "exploit-walkthrough": "Exploit walkthrough",
  "malware-or-threat-intel": "Malware or threat intel",
  "incident-postmortem": "Incident postmortem",
  "tool-or-release": "Tool or release",
  "benchmark-or-evaluation": "Benchmark or evaluation",
  "engineering-practice": "Engineering practice",
  "detection-engineering": "Detection engineering",
  "research-summary": "Research summary",
  "explainer-or-tutorial": "Explainer or tutorial",
  "opinion-or-strategy": "Opinion or strategy",
  other: "Other",
};

const SUBTOPIC_LABELS: Record<string, string> = {
  "botnets-and-ddos": "Botnets and DDoS",
  "ci-cd-and-build-compromise": "CI/CD and build compromise",
  "authentication-authorization": "Authentication and authorization",
  "server-side-request-forgery": "Server-side request forgery (SSRF)",
  "race-state-order": "Races, state and ordering",
  "ml-privacy-integrity": "ML privacy and integrity",
  "pki-and-certificates": "PKI and certificates",
};

export function postTypeLabel(slug: string): string {
  return POST_TYPE_LABELS[slug] ?? slug;
}

/** "memory-safety" → "Memory safety"; "other: agent memory design" → "agent memory design". */
export function subtopicLabel(slug: string): string {
  if (slug.startsWith("other:")) return slug.slice("other:".length).trim();
  if (SUBTOPIC_LABELS[slug]) return SUBTOPIC_LABELS[slug];
  const words = slug.replace(/-/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** "https://www.wiz.io/blog/x" → "wiz.io". */
export function publisherHost(url: string | null | undefined): string | null {
  if (!url) return null;
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return null;
  }
}

function comparable(value: string): string {
  return value.normalize("NFKC").toLowerCase().replace(/[^\p{L}\p{N}]+/gu, " ").trim();
}

/**
 * The published title, when it says something the display title does not
 * (a translated post). Titles that only add a " | Publisher" suffix are hidden.
 */
export function distinctOriginalTitle(title: string, original: string | null | undefined): string | null {
  if (!original) return null;
  return comparable(original).startsWith(comparable(title)) ? null : original;
}

/** Analytics `surface` for clicks in Trending's industry block. */
export const TRENDING_INDUSTRY_SURFACE = "trending_industry";
export const ALL_INDUSTRY_POSTS_HREF = "/catalog?kind=post&order=featured";

/**
 * An "Editor's pick": a post the editor pinned (`curated_pin`). The first three pins fill Trending's
 * Editor's picks block; the others rank in the feed like any post. Posts marked `curated` without a
 * pin get no badge, so the badge means the same on every card.
 */
export function isEditorsPick(post: { curated_pin?: number | null } | null | undefined): boolean {
  return (post?.curated_pin ?? 0) > 0;
}

/** Reviewed repository roles for a post's code links, in display order (the post's own code first). */
export const REPOSITORY_ROLES = ["original", "supporting", "target", "dependency"] as const;
export type RepositoryRole = (typeof REPOSITORY_ROLES)[number];

/** Group heading on a post page: what the repository is to this post. */
export const POST_REPOSITORY_ROLE_LABELS: Record<RepositoryRole, string> = {
  original: "Code released with this post",
  supporting: "Also uses",
  target: "Targets / tests against",
  dependency: "Depends on",
};

/** Group heading on a repository's references page: how each work relates to the repository. */
export const REFERENCE_ROLE_LABELS: Record<string, string> = {
  original: "Released by",
  supporting: "Used by",
  target: "Targeted or tested by",
  dependency: "A dependency of",
  unspecified: "Also linked from",
};

/** Repositories grouped by role in REPOSITORY_ROLES order; links without a known role come last as "other". */
export function groupRepositoriesByRole<T extends { role?: string | null }>(
  repositories: T[],
): Array<{ role: RepositoryRole | "other"; repositories: T[] }> {
  const known = new Set<string>(REPOSITORY_ROLES);
  const groups = REPOSITORY_ROLES.map((role) => ({
    role: role as RepositoryRole | "other",
    repositories: repositories.filter((repository) => repository.role === role),
  }));
  groups.push({ role: "other", repositories: repositories.filter((repository) => !known.has(repository.role ?? "")) });
  return groups.filter((group) => group.repositories.length > 0);
}

/** A star count is shown only once it has been observed; unfetched repositories carry a placeholder 0. */
export function knownStars(repository: { num_stars?: number | null; num_stars_updated_at?: string | null }): number | null {
  return repository.num_stars_updated_at ? repository.num_stars ?? null : null;
}

/** In-site page listing the papers and posts that reference a GitHub repository. */
export function repositoryReferencesHref(owner: string, name: string): string {
  return `/repos/${encodeURIComponent(owner)}/${encodeURIComponent(name)}`;
}
