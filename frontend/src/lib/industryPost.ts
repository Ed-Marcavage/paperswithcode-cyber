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
