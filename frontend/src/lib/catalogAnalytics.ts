import posthog, { type PostHogConfig } from "posthog-js";
import { isDiscoveryCatalog } from "./apiUrl";
import type { Axis, DiscoveryWork } from "./api/discovery";
import { catalogRecordingOptions, posthogPrivacyOptions } from "./posthogPrivacy";

type Resource = "pdf" | "reader" | "cached_text" | "source" | "code" | "artifact";
const assistantActions = ["opened", "closed", "asked_from_landing", "message_sent", "answer_done", "link_clicked", "new_chat", "feedback_given", "limit_hit", "error",
  "topic_chosen", "slash_menu_used", "follow_up_clicked", "chat_renamed", "chat_deleted"] as const;
type AssistantAction = typeof assistantActions[number];
type AssistantSurface = "landing" | "panel" | "chat_page";
type CatalogEvent = "catalog_kind_selected" | "catalog_sort_selected" | "catalog_filters_opened";
type Event = "$pageview" | "visit_engaged" | "catalog_navigation" | "taxonomy_selected" | "paper_opened" | "paper_link_clicked" | "paper_resource_clicked" | CatalogEvent | `assistant_${AssistantAction}`;
const assistantEvents = new Set(assistantActions.map(action => `assistant_${action}`));
// Coarse browser, OS and device type, plus the user agent they are parsed from: PostHog's traffic
// classification ($virt_is_bot / $virt_traffic_type) reads the user agent, and without it every visit
// is labelled Automation. No browser version, screen size, URL, referrer or location goes with them.
const deviceFields = ["$browser", "$os", "$device_type", "$raw_user_agent"];
const assistantFields = new Set(["token", "distinct_id", "$device_id", "$session_id", "$lib", "$lib_version", "catalog_environment", "surface", ...deviceFields]);
// A topic slug is a fixed catalog identifier, never chat text; only assistant_topic_chosen carries one.
const topicSlug = /^[a-z0-9][a-z0-9-]{0,63}$/;
/**
 * The only extra properties an assistant event may carry, each a fixed label chosen in code
 * (never chat text, a title or an address): which topic and how it was picked, how the panel
 * was opened, whether an answer link stays on the site, which thumb was pressed, and whether
 * a message starts a new chat (so questions per chat can be counted without a chat id).
 */
const assistantExtras: Partial<Record<AssistantAction, Record<string, readonly string[] | RegExp>>> = {
  topic_chosen: { topic: topicSlug, via: ["chip", "slash"] },
  opened: { via: ["ask_button", "try_chat"] },
  link_clicked: { link: ["site", "external"] },
  feedback_given: { rating: ["good", "bad"] },
  message_sent: { chat: ["new", "existing"] },
};
export type AssistantExtra = { topic?: string; via?: string; link?: "site" | "external"; rating?: "good" | "bad"; chat?: "new" | "existing" };
function allowedExtra(action: string, key: string, value: unknown) {
  const rule = assistantExtras[action as AssistantAction]?.[key];
  if (!rule || typeof value !== "string") return false;
  return rule instanceof RegExp ? rule.test(value) : rule.includes(value);
}
const fields = new Set(["token", "distinct_id", "$device_id", "$session_id", "$lib", "$lib_version",
  "page", "destination", "surface", "axis", "value", "paper_id", "paper_title", "resource", "link_part",
  "topic", "target", "contribution", "kind", "year", "catalog_environment",
  "referral_source", "referral_campaign", "referral_link", "referral_domain", ...deviceFields]);
// visit_engaged only: whole seconds from the landing pageview, and which fixed signal completed it.
const engagedTriggers = ["scroll", "click", "key", "second_page"] as const;
type EngagedTrigger = typeof engagedTriggers[number];
function allowedEngagedExtra(key: string, value: unknown) {
  if (key === "trigger") return engagedTriggers.includes(value as EngagedTrigger);
  return key === "seconds_to_engage" && Number.isInteger(value) && (value as number) >= 0;
}
const events = new Set<Event>(["$pageview", "visit_engaged", "catalog_navigation", "taxonomy_selected", "paper_opened", "paper_link_clicked", "paper_resource_clicked",
  "catalog_kind_selected", "catalog_sort_selected", "catalog_filters_opened"]);
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
    if (!event || (!events.has(event.event as Event) && !assistantEvents.has(event.event)) || !event.properties.catalog_environment) return null;
    const assistant = assistantEvents.has(event.event);
    if (assistant && !["landing", "panel", "chat_page"].includes(String(event.properties.surface))) return null;
    // posthog-js 1.418 sends a returning browser's first event after the 30-minute idle timeout
    // with $session_id null (the stale session is cleared mid-check). Asking for the id starts
    // the new session here, the one its recording uses, so the landing pageview joins it.
    if (event.properties.$session_id === null) event.properties.$session_id = posthog.get_session_id() || null;
    // The SDK otherwise adds raw URLs, referrers, search strings and initial person properties.
    const action = event.event.slice("assistant_".length);
    const properties = Object.fromEntries(Object.entries(event.properties).filter(([key, value]) => (assistant ? assistantFields : fields).has(key)
      || (assistant && allowedExtra(action, key, value))
      || (event.event === "visit_engaged" && allowedEngagedExtra(key, value))));
    return { uuid: event.uuid, timestamp: event.timestamp, event: event.event,
      properties: { ...properties, $geoip_disable: true, $process_person_profile: false } };
  },
} satisfies Partial<PostHogConfig>;

/**
 * Opt-out by address: opening any page with `?internal=1` remembers this browser as opted out
 * (localStorage), and `?internal=0` forgets it. An opted-out browser is treated exactly like one
 * sending Do Not Track: PostHog is never started, so no events and no session recording.
 */
const OPT_OUT_KEY = "pwc_catalog_internal";
export function catalogOptedOut(search: string = window.location.search) {
  const flag = new URLSearchParams(search).get("internal");
  if (flag === "1") store("localStorage", OPT_OUT_KEY, "1");
  else if (flag === "0") { try { window.localStorage.removeItem(OPT_OUT_KEY); } catch { /* blocked storage */ } }
  // The address itself counts, so a browser with blocked storage is still opted out on that page.
  return flag === "1" || (flag !== "0" && stored("localStorage", OPT_OUT_KEY) === "1");
}
export function catalogPrivacySignal() {
  return catalogOptedOut() || navigator.doNotTrack === "1" || Boolean((navigator as Navigator & {globalPrivacyControl?: boolean}).globalPrivacyControl);
}
export function catalogPage(path: string) {
  const [, section, detail] = path.split("/");
  if (!section) return "trending";
  if (section === "chat") return "chat";
  // The index and one entry are different pages; the entry's id or slug is never sent.
  if (section === "developers") return detail ? "developer" : "developers";
  if (section === "organizations") return "organizations";
  if (section === "orgs") return "organization";
  return ["catalog", "mcp", "personal-agents", "paper", "pdf", "papers", "tasks", "privacy", "docs"].includes(section) ? section : "other";
}
/**
 * The address a pageview stands for. A chat's own address (/chat/<id>) is the same chat page:
 * the new chat's id replacing /chat, or picking another chat from the list, is not a new page.
 */
export function catalogPageKey(path: string) {
  return path === "/chat" || path.startsWith("/chat/") ? "/chat" : path;
}
function captureEnabled() {
  return isDiscoveryCatalog() && Boolean(import.meta.env.VITE_POSTHOG_PROJECT_TOKEN) && !catalogPrivacySignal();
}
function capture(event: Event, properties: Record<string, unknown>) {
  if (!captureEnabled()) return;
  posthog.capture(event, { ...properties, catalog_environment: import.meta.env.VITE_CATALOG_ANALYTICS_ENV || "preview" });
}
/**
 * Deliberately accepts no question, answer, title, note, URL, run or browser ID. The only
 * extras are the fixed labels in assistantExtras, such as the topic slug on topic_chosen (a
 * catalog identifier); follow_up_clicked does not say which suggestion was clicked.
 */
export function assistantEvent(action: AssistantAction, surface: AssistantSurface, extra: AssistantExtra = {}) {
  if (!assistantActions.includes(action) || !["landing", "panel", "chat_page"].includes(surface)) return;
  const allowed = Object.fromEntries(Object.entries(extra).filter(([key, value]) => allowedExtra(action, key, value)));
  capture(`assistant_${action}`, { surface, ...allowed });
}
/** Trending's Papers or Posts switch. */
export function catalogKindSelected(kind: "paper" | "post") {
  capture("catalog_kind_selected", { page: "trending", kind });
}
/** A sort button or menu on the Organizations or Developers index; `value` is the sort's fixed key. */
export function catalogSortSelected(page: "organizations" | "developers", value: string) {
  if (/^[a-z_]{1,32}$/.test(value)) capture("catalog_sort_selected", { page, value });
}
/** The phone Filters sheet on Browse catalog. */
export function catalogFiltersOpened() {
  capture("catalog_filters_opened", { page: "catalog" });
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
/**
 * "Engaged visit": one `visit_engaged` event per PostHog session, sent once the visitor has stayed
 * ENGAGED_AFTER_MS since the session's first pageview in this tab AND has scrolled, clicked, pressed
 * a key (the visitor's own input only, never scripted events) or opened a second page. It carries the landing pageview's
 * labels (page type and referral labels), the seconds it took and which signal completed it:
 * never an address, a search term or page text.
 *
 * The landing labels and start time are kept in sessionStorage so a reload continues the same
 * visit; the session that already sent the event is remembered in localStorage (where PostHog
 * keeps the session id itself), so a reload or a second tab in that session does not send it again.
 */
export const ENGAGED_AFTER_MS = 15_000;
const ENGAGED_VISIT_KEY = "pwc_catalog_visit";
const ENGAGED_SENT_KEY = "pwc_catalog_visit_engaged";
type Visit = { session: string | null; startedAt: number; landing: Record<string, unknown> };
let visit: Visit | undefined;
let engagedTrigger: EngagedTrigger | undefined;
let engagedSent = false;
let engagedTimer: ReturnType<typeof setTimeout> | undefined;
function stored(storage: "sessionStorage" | "localStorage", key: string): string | null {
  try { return window[storage].getItem(key); } catch { return null; }
}
function store(storage: "sessionStorage" | "localStorage", key: string, value: string) {
  try { window[storage].setItem(key, value); } catch { /* private window or blocked storage: memory only */ }
}
function sessionId(): string | null {
  try { return posthog.get_session_id() || null; } catch { return null; }
}
function sendEngagedWhenReady() {
  if (!visit || !engagedTrigger || engagedSent) return;
  const elapsed = Date.now() - visit.startedAt;
  if (elapsed < ENGAGED_AFTER_MS) {
    if (engagedTimer === undefined) engagedTimer = setTimeout(() => { engagedTimer = undefined; sendEngagedWhenReady(); }, ENGAGED_AFTER_MS - elapsed);
    return;
  }
  engagedSent = true;
  stopEngagedListeners();
  const session = sessionId();
  // Another tab, or this tab before a reload, already sent it for this session.
  if (session && stored("localStorage", ENGAGED_SENT_KEY) === session) return;
  if (!captureEnabled()) return;
  if (session) store("localStorage", ENGAGED_SENT_KEY, session);
  capture("visit_engaged", { ...visit.landing, seconds_to_engage: Math.round(elapsed / 1000), trigger: engagedTrigger });
}
function engagedSignal(trigger: EngagedTrigger) {
  engagedTrigger ??= trigger;
  sendEngagedWhenReady();
}
// The browser also raises `scroll` when a script or a reload's scroll restoration moves the page, so
// scrolling counts through what the visitor does: the wheel or trackpad, a touch drag, or a scroll
// while the pointer was pressed shortly before (dragging a scrollbar).
const SCROLLBAR_DRAG_MS = 10_000;
let pointerPressedAt = -Infinity;
type BrowserEvent = globalThis.Event;
const engagedListeners: Array<[keyof WindowEventMap, (event: BrowserEvent) => void]> = [
  ["wheel", event => { if (event.isTrusted) engagedSignal("scroll"); }],
  ["touchmove", event => { if (event.isTrusted) engagedSignal("scroll"); }],
  ["pointerdown", event => { if (event.isTrusted) pointerPressedAt = Date.now(); }],
  ["scroll", event => { if (event.isTrusted && Date.now() - pointerPressedAt < SCROLLBAR_DRAG_MS) engagedSignal("scroll"); }],
  ["click", event => { if (event.isTrusted) engagedSignal("click"); }],
  ["keydown", event => { if (event.isTrusted) engagedSignal("key"); }],
];
function stopEngagedListeners() {
  for (const [name, listener] of engagedListeners) window.removeEventListener(name, listener, true);
}
/** Called with every pageview; `landing` is the labels that pageview carries. */
function trackEngagedVisit(landing: Record<string, unknown>) {
  if (engagedSent || !captureEnabled()) return;
  if (visit) return engagedSignal("second_page");
  const session = sessionId();
  try {
    // A reload inside the same session continues the visit it started.
    const saved = JSON.parse(stored("sessionStorage", ENGAGED_VISIT_KEY) || "null") as Visit | null;
    if (saved && session && saved.session === session && typeof saved.startedAt === "number") visit = saved;
  } catch { /* unreadable: start a new visit */ }
  if (!visit) {
    visit = { session, startedAt: Date.now(), landing };
    store("sessionStorage", ENGAGED_VISIT_KEY, JSON.stringify(visit));
  }
  // Capture phase: a scroll inside any scrolling panel counts, and scroll events do not bubble.
  for (const [name, listener] of engagedListeners) window.addEventListener(name, listener, { capture: true, passive: true });
}
// document.referrer stays the same across client-side navigations: send it with the landing pageview only.
let landed = false;
export function catalogPageview(path: string) {
  const domain = landed ? undefined : catalogReferrerDomain(document.referrer, window.location.hostname);
  landed = true;
  const properties = {page: catalogPage(path), ...catalogReferral(window.location.search),
    ...(domain ? {referral_domain: domain} : {})};
  capture("$pageview", properties);
  trackEngagedVisit(properties);
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
/** The site's own off-site links (its GitHub repository, issue tracker, CLI and Discord), which otherwise leave no trace. */
export function outboundNavigation(surface: "footer" | "sidebar" | "mcp_page" | "header", destination: "github" | "feedback" | "pwc_cli" | "discord") {
  capture("catalog_navigation", {surface, destination});
}
export function taxonomySelected(axis: Axis | "domain", value: string | undefined, surface: "catalog_filter" | "top_domains" | "paper_tag") {
  if (value) capture("taxonomy_selected", {axis, value, surface});
}
export function paperOpened(paper: DiscoveryWork) {
  capture("paper_opened", { paper_id: paper.paper_id, paper_title: paper.title, ...paper.facets });
}
export function resourceClicked(paperId: string, resource: Resource, surface: "feed" | "paper" | "reader" = "paper", part?: "screenshot" | "title") {
  capture("paper_resource_clicked", {paper_id: paperId, resource, surface, ...(part ? {link_part: part} : {})});
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
