import posthog, { type PostHogConfig } from "posthog-js";
import { isDiscoveryCatalog } from "./apiUrl";
import type { Axis, DiscoveryWork } from "./api/discovery";
import { catalogRecordingOptions, posthogPrivacyOptions } from "./posthogPrivacy";

type Resource = "pdf" | "reader" | "cached_text" | "source" | "code" | "artifact";
type Event = "$pageview" | "catalog_navigation" | "taxonomy_selected" | "paper_opened" | "paper_link_clicked" | "paper_resource_clicked";
const fields = new Set(["token", "distinct_id", "$device_id", "$session_id", "$lib", "$lib_version",
  "page", "destination", "surface", "axis", "value", "paper_id", "paper_title", "resource", "link_part",
  "topic", "target", "contribution", "kind", "year", "catalog_environment",
  "referral_source", "referral_campaign", "referral_link", "referral_domain"]);
const events = new Set<Event>(["$pageview", "catalog_navigation", "taxonomy_selected", "paper_opened", "paper_link_clicked", "paper_resource_clicked"]);
// Session replay batches: the recorder's own fields only.
const snapshotFields = new Set(["token", "distinct_id", "$session_id", "$window_id", "$snapshot_bytes",
  "$snapshot_data", "$snapshot_host", "$lib", "$lib_version"]);
export const catalogOptions = {
  ...posthogPrivacyOptions,
  capture_pageview: false, person_profiles: "never", persistence: "localStorage",
  save_referrer: false, save_campaign_params: false, respect_dnt: true,
  // Session replay. Recording starts in startCatalogRecording once the bundled
  // recorder is loaded, and only if the PostHog project has replay switched on;
  // that switch arrives in the project's remote config, which needs flags enabled.
  // Feature-flag requests, heatmaps, surveys and console capture stay off.
  advanced_disable_flags: false, advanced_disable_feature_flags: true, remote_config_refresh_interval_ms: 0,
  capture_heatmaps: false, disable_surveys: true, disable_product_tours: true, disable_conversations: true,
  enable_recording_console_log: false, logs: { captureConsoleLogs: false },
  session_recording: catalogRecordingOptions,
  before_send(event) {
    if (event?.event === "$snapshot") {
      return { uuid: event.uuid, timestamp: event.timestamp, event: event.event,
        properties: Object.fromEntries(Object.entries(event.properties).filter(([key]) => snapshotFields.has(key))) };
    }
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
/** Recognize our public README links without collecting arbitrary campaign or URL text. */
export function catalogReferral(search: string) {
  const params = new URLSearchParams(search);
  if (params.get("utm_source") !== "github" || params.get("utm_medium") !== "readme" ||
      params.get("utm_campaign") !== "awesome-security-agent-harnesses") return {};
  const link = params.get("utm_content");
  return {
    referral_source: "github",
    referral_campaign: "awesome-security-agent-harnesses",
    ...(link === "catalog" || link === "mcp" ? {referral_link: link} : {}),
  };
}
/**
 * The referring site's domain ("news.ycombinator.com"), never its path or query;
 * nothing for this site itself, a missing referrer or a non-web referrer.
 */
export function catalogReferrerDomain(referrer: string, ownHost: string): string | undefined {
  let url: URL;
  try { url = new URL(referrer); } catch { return undefined; }
  if (url.protocol !== "https:" && url.protocol !== "http:") return undefined;
  const domain = url.hostname.toLowerCase().replace(/^www\./, "");
  if (!domain || domain === ownHost.toLowerCase().replace(/^www\./, "")) return undefined;
  return domain;
}
// document.referrer stays the same across client-side navigations: send it with the landing pageview only.
let landed = false;
export function catalogPageview(path: string) {
  const domain = landed ? undefined : catalogReferrerDomain(document.referrer, window.location.hostname);
  landed = true;
  capture("$pageview", {page: catalogPage(path), ...catalogReferral(window.location.search),
    ...(domain ? {referral_domain: domain} : {})});
}

type PosthogExtensions = { __PosthogExtensions__?: { rrwebPlugins?: Record<string, unknown> } };
/**
 * Load PostHog's recorder from this site's own bundle (external script loading
 * stays off), drop its console-log and network plugins so project settings
 * cannot turn those on, then allow replay. PostHog records only if the project
 * has replay switched on. Call after posthog.init.
 */
export async function startCatalogRecording(client: Pick<typeof posthog, "startSessionRecording"> = posthog) {
  await import("posthog-js/dist/posthog-recorder");
  const extensions = (window as Window & PosthogExtensions).__PosthogExtensions__;
  if (extensions) extensions.rrwebPlugins = {};
  client.startSessionRecording();
}
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
