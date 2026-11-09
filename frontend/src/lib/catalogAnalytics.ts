import posthog, { type PostHogConfig } from "posthog-js";
import { isDiscoveryCatalog } from "./apiUrl";
import type { Axis, DiscoveryWork } from "./api/discovery";
import { posthogPrivacyOptions } from "./posthogPrivacy";

type Resource = "pdf" | "reader" | "cached_text" | "source" | "code" | "artifact";
type Event = "$pageview" | "catalog_navigation" | "taxonomy_selected" | "paper_opened" | "paper_link_clicked" | "paper_resource_clicked";
const fields = new Set(["token", "distinct_id", "$device_id", "$session_id", "$lib", "$lib_version",
  "page", "destination", "surface", "axis", "value", "paper_id", "paper_title", "resource", "link_part",
  "topic", "target", "contribution", "kind", "year", "catalog_environment"]);
const events = new Set<Event>(["$pageview", "catalog_navigation", "taxonomy_selected", "paper_opened", "paper_link_clicked", "paper_resource_clicked"]);
export const catalogOptions = {
  ...posthogPrivacyOptions,
  capture_pageview: false, person_profiles: "never", persistence: "localStorage",
  save_referrer: false, save_campaign_params: false, respect_dnt: true,
  before_send(event) {
    if (!event || !events.has(event.event as Event) || !event.properties.catalog_environment) return null;
    // The SDK otherwise adds raw URLs, referrers, search strings and initial person properties.
    const properties = Object.fromEntries(Object.entries(event.properties).filter(([key]) => fields.has(key)));
    return { uuid: event.uuid, timestamp: event.timestamp, event: event.event,
      properties: { ...properties, $geoip_disable: true, $process_person_profile: false } };
  },
} satisfies Partial<PostHogConfig>;

export function catalogPrivacySignal() {
  return navigator.doNotTrack === "1" || Boolean((navigator as Navigator & {globalPrivacyControl?: boolean}).globalPrivacyControl);
}
export function catalogPage(path: string) {
  const section = path.split("/")[1];
  return !section ? "trending" : ["catalog", "mcp", "personal-agents", "paper", "pdf", "papers", "tasks", "privacy", "docs"].includes(section) ? section : "other";
}
function capture(event: Event, properties: Record<string, unknown>) {
  if (!isDiscoveryCatalog() || !import.meta.env.VITE_POSTHOG_PROJECT_TOKEN || catalogPrivacySignal()) return;
  posthog.capture(event, { ...properties, catalog_environment: import.meta.env.VITE_CATALOG_ANALYTICS_ENV || "preview" });
}
export function catalogPageview(path: string) { capture("$pageview", {page: catalogPage(path)}); }
export function catalogNavigation(to: string) {
  if (to === "/catalog" || to === "/mcp" || to === "/personal-agents") capture("catalog_navigation", {surface: "top_nav", destination: to.slice(1)});
}
export function taxonomySelected(axis: Axis | "domain", value: string | undefined, surface: "catalog_filter" | "top_domains" | "paper_tag") {
  if (value) capture("taxonomy_selected", {axis, value, surface});
}
export function paperOpened(paper: DiscoveryWork) {
  capture("paper_opened", { paper_id: paper.paper_id, paper_title: paper.title, ...paper.facets });
}
export function resourceClicked(paperId: string, resource: Resource, surface: "feed" | "paper" | "reader" = "paper") {
  capture("paper_resource_clicked", {paper_id: paperId, resource, surface});
}

/** Classify only destinations whose format or repository path is explicit. */
export function externalResource(href: string, fallback: "source" | "artifact"): Resource {
  let url: URL;
  try { url = new URL(href); } catch { return fallback; }
  if (/\.pdf$/i.test(url.pathname) || (url.hostname === "arxiv.org" && url.pathname.startsWith("/pdf/"))) return "pdf";
  if (["github.com", "gitlab.com"].includes(url.hostname) && url.pathname.split("/").filter(Boolean).length >= 2) return "code";
  return fallback;
}

/** Count link activation at the source, even if the destination opens in another tab. */
export function paperLinkHandlers(id: string, title: string, part: "title" | "thumbnail",
  surface?: string, facets?: DiscoveryWork["facets"]) {
  function activated() {
    capture("paper_link_clicked", {paper_id: id, paper_title: title, link_part: part,
      surface: surface ?? catalogPage(window.location.pathname), ...facets});
  }
  return {
    onClick: (e: {button: number}) => { if (e.button === 0) activated(); },
    onAuxClick: (e: {button: number}) => { if (e.button === 1) activated(); },
  };
}
