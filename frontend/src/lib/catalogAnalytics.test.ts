import { expect, it } from "vitest";
import { assistantEvent, catalogFiltersOpened, catalogKindSelected, catalogOptedOut, catalogOptions, catalogPage, catalogPageKey, catalogReferral, catalogReferrerDomain, catalogSortSelected, externalResource, outboundNavigation, resourceClicked } from "./catalogAnalytics";
it("retains the paper measurements while dropping SDK URL, search, referrer, profile and location properties", () => {
  const event = { uuid: "test", event: "paper_opened", properties: {
    distinct_id: "anonymous", $current_url: "https://example.org/?q=private", $referrer: "private",
    catalog_environment: "preview", paper_id: "134", topic: ["repair"], $set_once: {email:"private"},
  }, $set: { email: "private" } };
  const sent = catalogOptions.before_send(event);
  expect(sent?.properties).toEqual({ distinct_id: "anonymous", catalog_environment: "preview", paper_id: "134",
    topic: ["repair"], $geoip_disable: true, $process_person_profile: false });
  expect(sent).not.toHaveProperty("$set");
  expect(catalogOptions.before_send({ ...event, event: "$autocapture" })).toBeNull();
  expect(catalogOptions.before_send({ ...event, properties: {} })).toBeNull();
});
it("keeps browser, OS, device type and user agent, but not browser version, screen size or location", () => {
  const device = { $browser: "Chrome", $os: "Mac OS X", $device_type: "Desktop",
    $raw_user_agent: "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36" };
  const extra = { $browser_version: 142, $os_version: "10.15.7", $screen_height: 900, $screen_width: 1440,
    $viewport_width: 1440, $timezone: "America/New_York", $browser_language: "en-US", $ip: "203.0.113.1" };
  for (const [event, labels] of [["$pageview", { page: "trending" }], ["assistant_opened", { surface: "panel", via: "ask_button" }]] as const) {
    const sent = catalogOptions.before_send({ uuid: "test", event, properties: {
      distinct_id: "anonymous", catalog_environment: "preview", ...labels, ...device, ...extra } });
    expect(sent?.properties).toEqual({ distinct_id: "anonymous", catalog_environment: "preview", ...labels, ...device,
      $geoip_disable: true, $process_person_profile: false });
  }
});
it("lets replay batches through with only the recorder's fields", () => {
  const sent = catalogOptions.before_send({ uuid: "test", event: "$snapshot", properties: {
    token: "phc_test", distinct_id: "anonymous", $session_id: "s", $window_id: "w", $snapshot_bytes: 10,
    $snapshot_data: [{ type: 4 }], $snapshot_host: "catalog.example", $lib: "web", $lib_version: "1",
    $current_url: "https://catalog.example/?q=private", $referrer: "private", $config_defaults: "2026-05-30",
  } } as never);
  expect(Object.keys(sent?.properties ?? {}).sort()).toEqual(["$lib", "$lib_version", "$session_id", "$snapshot_bytes",
    "$snapshot_data", "$snapshot_host", "$window_id", "distinct_id", "token"]);
});

it("turns on replay for the catalog only through bundled code, with autocapture, heatmaps, console and flags off", () => {
  expect(catalogOptions).toMatchObject({
    autocapture: false, capture_heatmaps: false, capture_dead_clicks: false, capture_performance: false,
    enable_recording_console_log: false, disable_external_dependency_loading: true,
    advanced_disable_flags: false, advanced_disable_feature_flags: true, disable_surveys: true,
    disable_session_recording: true, respect_dnt: true,
    session_recording: { maskAllInputs: true, recordHeaders: false, recordBody: false },
  });
});

it("starts recording with the recorder bundled and its console and network plugins removed", async () => {
  const { startCatalogRecording } = await import("./catalogAnalytics");
  const client = { startSessionRecording: (await import("vitest")).vi.fn() };
  await startCatalogRecording(client as never);
  const extensions = (window as unknown as { __PosthogExtensions__: Record<string, unknown> }).__PosthogExtensions__;
  expect(typeof (extensions.rrweb as { record?: unknown }).record).toBe("function");
  expect(typeof extensions.initSessionRecording).toBe("function");
  expect(extensions.rrwebPlugins).toEqual({});
  expect(client.startSessionRecording).toHaveBeenCalledWith();
});

it("keeps only the referring site's domain, and nothing for this site or non-web referrers", () => {
  expect(catalogReferrerDomain("https://news.ycombinator.com/item?id=1", "catalog.example")).toBe("news.ycombinator.com");
  expect(catalogReferrerDomain("https://www.Google.com/search?q=private", "catalog.example")).toBe("google.com");
  expect(catalogReferrerDomain("https://catalog.example/paper/1", "catalog.example")).toBeUndefined();
  expect(catalogReferrerDomain("https://www.catalog.example/", "catalog.example")).toBeUndefined();
  expect(catalogReferrerDomain("android-app://com.example/", "catalog.example")).toBeUndefined();
  expect(catalogReferrerDomain("", "catalog.example")).toBeUndefined();
  const sent = catalogOptions.before_send({uuid: "test", event: "$pageview", properties: {
    catalog_environment: "production", page: "trending", referral_domain: "news.ycombinator.com", $referrer: "https://news.ycombinator.com/item?id=1",
  }});
  expect(sent?.properties).toEqual({catalog_environment: "production", page: "trending", referral_domain: "news.ycombinator.com",
    $geoip_disable: true, $process_person_profile: false});
});

it("page categories never include search terms or arbitrary path segments", () => {
  expect(catalogPage("/paper/2603.04915")).toBe("paper");
  expect(catalogPage("/unknown/private")).toBe("other");
  expect(catalogPage("/")).toBe("trending");
  expect(catalogPage("/chat")).toBe("chat");
  expect(catalogPage("/chat/0b6f2c1e-private")).toBe("chat");
  expect(catalogPage("/developers")).toBe("developers");
  expect(catalogPage("/developers/private-login")).toBe("developer");
  expect(catalogPage("/organizations")).toBe("organizations");
  expect(catalogPage("/orgs/private-org")).toBe("organization");
});

it("counts the chat page once, whatever chat id its address carries", () => {
  expect(catalogPageKey("/chat")).toBe("/chat");
  expect(catalogPageKey("/chat/3f1c")).toBe("/chat");
  expect(catalogPageKey("/chatter")).toBe("/chatter");
  expect(catalogPageKey("/paper/1")).toBe("/paper/1");
});

it("gives a returning browser's first event the new session id instead of null", async () => {
  const { vi } = await import("vitest");
  const posthog = (await import("posthog-js")).default;
  const id = vi.spyOn(posthog, "get_session_id").mockReturnValue("01a1-new-session");
  try {
    const sent = catalogOptions.before_send({ uuid: "test", event: "$pageview", properties: {
      catalog_environment: "production", page: "trending", $session_id: null } });
    expect(sent?.properties.$session_id).toBe("01a1-new-session");
    const kept = catalogOptions.before_send({ uuid: "test", event: "$pageview", properties: {
      catalog_environment: "production", page: "trending", $session_id: "01a1-existing" } });
    expect(kept?.properties.$session_id).toBe("01a1-existing");
    expect(id).toHaveBeenCalledTimes(1);
  } finally { id.mockRestore(); }
});

it("lets assistant events carry only their own fixed labels", () => {
  const send = (event: string, properties: Record<string, unknown>) =>
    catalogOptions.before_send({ uuid: "test", event, properties: { catalog_environment: "preview", surface: "chat_page", ...properties } })?.properties;
  const base = { catalog_environment: "preview", surface: "chat_page", $geoip_disable: true, $process_person_profile: false };
  expect(send("assistant_link_clicked", { link: "external", href: "https://private.example/" })).toEqual({ ...base, link: "external" });
  expect(send("assistant_link_clicked", { link: "https://private.example/" })).toEqual(base);
  expect(send("assistant_feedback_given", { rating: "bad", note: "private" })).toEqual({ ...base, rating: "bad" });
  expect(send("assistant_feedback_given", { rating: "private" })).toEqual(base);
  expect(send("assistant_topic_chosen", { topic: "fuzzing", via: "chip" })).toEqual({ ...base, topic: "fuzzing", via: "chip" });
  expect(send("assistant_opened", { via: "try_chat" })).toEqual({ ...base, via: "try_chat" });
  expect(send("assistant_opened", { via: "private text" })).toEqual(base);
  expect(send("assistant_message_sent", { chat: "new", question: "private" })).toEqual({ ...base, chat: "new" });
  // A label belongs to its own event only.
  expect(send("assistant_message_sent", { rating: "good", link: "site", via: "chip", topic: "fuzzing", chat: "c-123" })).toEqual(base);
  expect(send("assistant_answer_done", { chat: "new" })).toEqual(base);
  for (const event of ["assistant_closed", "assistant_chat_renamed", "assistant_chat_deleted"]) {
    expect(send(event, { title: "private" })).toEqual(base);
  }
});

it("records Trending's kind switch, index sorts, the filter sheet and the screenshot link", async () => {
  const { vi } = await import("vitest");
  const posthog = (await import("posthog-js")).default;
  vi.stubEnv("VITE_LOCAL_CATALOG", "true");
  vi.stubEnv("VITE_POSTHOG_PROJECT_TOKEN", "phc_test");
  const spy = vi.spyOn(posthog, "capture").mockReturnValue(undefined);
  try {
    catalogKindSelected("paper");
    catalogSortSelected("developers", "stars");
    catalogSortSelected("organizations", "Private Text");
    catalogFiltersOpened();
    resourceClicked("5294", "source", "paper", "screenshot");
    assistantEvent("link_clicked", "panel", { link: "site" });
    outboundNavigation("sidebar", "pwc_cli");
    outboundNavigation("mcp_page", "discord");
    expect(spy.mock.calls.map(call => call[0])).toEqual(["catalog_kind_selected", "catalog_sort_selected", "catalog_filters_opened",
      "paper_resource_clicked", "assistant_link_clicked", "catalog_navigation", "catalog_navigation"]);
    expect(spy).toHaveBeenCalledWith("catalog_navigation", expect.objectContaining({ surface: "mcp_page", destination: "discord" }));
    expect(spy).toHaveBeenCalledWith("catalog_sort_selected", expect.objectContaining({ page: "developers", value: "stars" }));
    expect(spy).toHaveBeenCalledWith("paper_resource_clicked", expect.objectContaining({ link_part: "screenshot", resource: "source" }));
    for (const [event, properties] of spy.mock.calls) {
      const sent = catalogOptions.before_send({ uuid: "test", event, properties: properties as Record<string, unknown> });
      expect(sent?.properties).toEqual({ ...(properties as object), $geoip_disable: true, $process_person_profile: false });
    }
  } finally { spy.mockRestore(); vi.unstubAllEnvs(); }
});

it("allows only the known README campaign and link labels, never arbitrary URL text", () => {
  const campaign = "?utm_source=github&utm_medium=readme&utm_campaign=awesome-security-agent-harnesses";
  const referral = catalogReferral(campaign + "&utm_content=catalog&q=private&email=private");
  expect(referral).toEqual({referral_source: "github", referral_campaign: "awesome-security-agent-harnesses", referral_link: "catalog"});
  expect(catalogReferral(campaign + "&utm_content=mcp")).toMatchObject({referral_link: "mcp"});
  expect(catalogReferral(campaign + "&utm_content=private")).not.toHaveProperty("referral_link");
  expect(catalogReferral("?utm_source=private&utm_campaign=awesome-security-agent-harnesses")).toEqual({});
  expect(catalogReferral("?utm_source=github&utm_medium=readme&utm_campaign=private")).toEqual({});
  expect(catalogReferral("")).toEqual({});
  const sent = catalogOptions.before_send({uuid: "test", event: "$pageview", properties: {
    catalog_environment: "production", ...referral, $current_url: "private", utm_content: "private", $referrer: "private",
  }});
  expect(sent?.properties).toEqual({catalog_environment: "production", ...referral, $geoip_disable: true, $process_person_profile: false});
});

it("attributes landing pageviews while preserving Do Not Track", async () => {
  const { vi } = await import("vitest");
  const { catalogPageview } = await import("./catalogAnalytics");
  const posthog = (await import("posthog-js")).default;
  const spy = vi.spyOn(posthog, "capture").mockReturnValue(undefined);
  vi.stubEnv("VITE_LOCAL_CATALOG", "true");
  vi.stubEnv("VITE_POSTHOG_PROJECT_TOKEN", "phc_test");
  const priorUrl = window.location.href;
  try {
    window.history.replaceState({}, "", "/mcp?utm_source=github&utm_medium=readme&utm_campaign=awesome-security-agent-harnesses&utm_content=mcp");
    catalogPageview("/mcp");
    expect(spy).toHaveBeenCalledWith("$pageview", expect.objectContaining({page: "mcp", referral_link: "mcp"}));
    window.history.replaceState({}, "", "/catalog");
    catalogPageview("/catalog");
    expect(spy.mock.calls.at(-1)?.[1]).not.toHaveProperty("referral_campaign");
    expect(spy.mock.calls.at(-1)?.[1]).not.toHaveProperty("referral_domain");
    vi.stubGlobal("navigator", {doNotTrack: "1"});
    catalogPageview("/catalog");
    expect(spy).toHaveBeenCalledTimes(2);
  } finally {
    window.history.replaceState({}, "", priorUrl);
    vi.restoreAllMocks(); vi.unstubAllEnvs(); vi.unstubAllGlobals();
  }
});

it("sends the referring domain with the landing pageview only", async () => {
  const { vi } = await import("vitest");
  vi.resetModules();
  const { catalogPageview } = await import("./catalogAnalytics");
  const posthog = (await import("posthog-js")).default;
  const spy = vi.spyOn(posthog, "capture").mockReturnValue(undefined);
  vi.stubEnv("VITE_LOCAL_CATALOG", "true");
  vi.stubEnv("VITE_POSTHOG_PROJECT_TOKEN", "phc_test");
  const referrer = vi.spyOn(document, "referrer", "get").mockReturnValue("https://news.ycombinator.com/item?id=42");
  try {
    catalogPageview("/");
    expect(spy.mock.calls.at(-1)?.[1]).toMatchObject({page: "trending", referral_domain: "news.ycombinator.com"});
    catalogPageview("/catalog");
    expect(spy.mock.calls.at(-1)?.[1]).not.toHaveProperty("referral_domain");
  } finally {
    referrer.mockRestore();
    vi.restoreAllMocks(); vi.unstubAllEnvs();
  }
});

it("counts a direct PDF or repository link, without treating its publisher landing page as a PDF", () => {
  expect(externalResource("https://arxiv.org/pdf/2603.04915", "source")).toBe("pdf");
  expect(externalResource("https://example.org/file.PDF?t=1", "artifact")).toBe("pdf");
  expect(externalResource("https://www.usenix.org/presentation/deng", "source")).toBe("source");
  expect(externalResource("https://github.com/openai/frontier-evals/tree/main/project/evmbench", "artifact")).toBe("code");
});

it("captures primary and middle activation once with the public title, not hover or context-menu actions", async () => {
  const { vi } = await import("vitest");
  const { paperLinkHandlers } = await import("./catalogAnalytics");
  const posthog = (await import("posthog-js")).default;
  vi.stubEnv("VITE_LOCAL_CATALOG", "true");
  vi.stubEnv("VITE_POSTHOG_PROJECT_TOKEN", "phc_test");
  const spy = vi.spyOn(posthog, "capture").mockReturnValue(undefined);
  try {
    const h = paperLinkHandlers("57", "Getting pwn'd by AI", "title", "papers", { topic: ["penetration-testing"] });
    expect(spy).not.toHaveBeenCalled();
    h.onAuxClick({button: 2});
    h.onClick({button: 0});
    h.onAuxClick({button: 1});
    expect(spy).toHaveBeenCalledTimes(2);
    expect(spy).toHaveBeenCalledWith("paper_link_clicked", expect.objectContaining({
      paper_id: "57", paper_title: "Getting pwn'd by AI", link_part: "title",
      topic: ["penetration-testing"], surface: "papers",
    }));
  } finally {
    spy.mockRestore();
    vi.unstubAllEnvs();
  }
});

/**
 * jsdom marks every dispatched event untrusted (as a page script's would be) and the flag cannot be
 * redefined, so a visitor's own input is delivered straight to the listeners the module registered.
 */
const gestureListeners = new Map<string, (event: { isTrusted: boolean }) => void>();
function trusted(type: string) {
  return { type, isTrusted: true };
}
function gesture(event: { type: string; isTrusted: boolean }) {
  gestureListeners.get(event.type)?.(event);
}
async function engagedVisitHarness(session = "session-1") {
  const { vi } = await import("vitest");
  vi.resetModules();
  window.sessionStorage.clear(); window.localStorage.clear();
  vi.useFakeTimers({ now: new Date("2026-11-17T00:00:00Z") });
  vi.stubEnv("VITE_LOCAL_CATALOG", "true");
  vi.stubEnv("VITE_POSTHOG_PROJECT_TOKEN", "phc_test");
  const analytics = await import("./catalogAnalytics");
  const posthog = (await import("posthog-js")).default;
  const spy = vi.spyOn(posthog, "capture").mockReturnValue(undefined);
  const id = vi.spyOn(posthog, "get_session_id").mockReturnValue(session);
  gestureListeners.clear();
  const add = window.addEventListener.bind(window);
  vi.spyOn(window, "addEventListener").mockImplementation((type: string, listener: unknown, options?: unknown) => {
    gestureListeners.set(type, listener as (event: { isTrusted: boolean }) => void);
    add(type, listener as EventListener, options as AddEventListenerOptions);
  });
  const engaged = () => spy.mock.calls.filter(([name]) => name === "visit_engaged");
  const done = () => { vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllEnvs(); vi.unstubAllGlobals(); window.sessionStorage.clear(); window.localStorage.clear(); };
  return { vi, analytics, engaged, id, done };
}
it("sends no engaged visit before 15 seconds, nor after them without a gesture or a second page", async () => {
  const { vi, analytics, engaged, done } = await engagedVisitHarness();
  try {
    analytics.catalogPageview("/");
    gesture(trusted("wheel"));
    vi.advanceTimersByTime(14_000);
    expect(engaged()).toHaveLength(0);
  } finally { done(); }
  const second = await engagedVisitHarness();
  try {
    second.analytics.catalogPageview("/");
    second.vi.advanceTimersByTime(120_000);
    // Scripted events and scrolling the browser does by itself (restoring a position) are not gestures.
    window.dispatchEvent(new Event("click")); window.dispatchEvent(new Event("wheel")); gesture(trusted("scroll"));
    expect(second.engaged()).toHaveLength(0);
  } finally { second.done(); }
});
it("sends one engaged visit once 15 seconds and a gesture are both there, with the landing labels", async () => {
  const { vi, analytics, engaged, done } = await engagedVisitHarness();
  const priorUrl = window.location.href;
  try {
    window.history.replaceState({}, "", "/mcp?utm_source=github&utm_medium=readme&utm_campaign=awesome-security-agent-harnesses&utm_content=mcp");
    analytics.catalogPageview("/mcp");
    vi.advanceTimersByTime(5_000);
    gesture(trusted("wheel"));
    gesture(trusted("click"));
    expect(engaged()).toHaveLength(0);
    vi.advanceTimersByTime(10_000);  // the gesture came first: sent as soon as the 15 seconds are up
    expect(engaged()).toEqual([["visit_engaged", { page: "mcp", referral_source: "github",
      referral_campaign: "awesome-security-agent-harnesses", referral_link: "mcp", seconds_to_engage: 15, trigger: "scroll",
      catalog_environment: "preview" }]]);
    // Nothing more in this session: more gestures, more pages, a reload, or another tab.
    gesture(trusted("keydown"));
    analytics.catalogPageview("/catalog");
    vi.advanceTimersByTime(60_000);
    expect(engaged()).toHaveLength(1);
    vi.resetModules();
    const reloaded = await import("./catalogAnalytics");
    reloaded.catalogPageview("/catalog");
    gesture(trusted("keydown"));
    vi.advanceTimersByTime(60_000);
    expect(engaged()).toHaveLength(1);
  } finally { window.history.replaceState({}, "", priorUrl); done(); }
});
it("sends the engaged visit on the gesture when the time passed first, or on a second page", async () => {
  const { vi, analytics, engaged, done } = await engagedVisitHarness();
  try {
    analytics.catalogPageview("/");
    vi.advanceTimersByTime(42_400);
    gesture(trusted("keydown"));
    expect(engaged()).toEqual([["visit_engaged", expect.objectContaining({ page: "trending", seconds_to_engage: 42, trigger: "key" })]]);
  } finally { done(); }
  const second = await engagedVisitHarness("session-2");
  try {
    second.analytics.catalogPageview("/");
    second.vi.advanceTimersByTime(20_000);
    second.analytics.catalogPageview("/paper/1");
    expect(second.engaged()).toEqual([["visit_engaged", expect.objectContaining({ page: "trending", seconds_to_engage: 20, trigger: "second_page" })]]);
  } finally { second.done(); }
});
it("sends no engaged visit under Do Not Track, and the allowlist keeps only its fixed labels", async () => {
  const { vi, analytics, engaged, done } = await engagedVisitHarness();
  try {
    vi.stubGlobal("navigator", { doNotTrack: "1" });
    analytics.catalogPageview("/");
    vi.advanceTimersByTime(20_000);
    gesture(trusted("click"));
    expect(engaged()).toHaveLength(0);
    const sent = analytics.catalogOptions.before_send({ uuid: "test", event: "visit_engaged", properties: {
      distinct_id: "anonymous", $session_id: "s", catalog_environment: "preview", page: "trending", referral_domain: "news.ycombinator.com",
      seconds_to_engage: 17, trigger: "scroll", $browser: "Chrome", $os: "Mac OS X", $device_type: "Desktop",
      $current_url: "https://example.org/?q=private", $referrer: "private", $pathname: "/paper/1" } });
    expect(sent?.properties).toEqual({ distinct_id: "anonymous", $session_id: "s", catalog_environment: "preview", page: "trending",
      referral_domain: "news.ycombinator.com", seconds_to_engage: 17, trigger: "scroll", $browser: "Chrome", $os: "Mac OS X",
      $device_type: "Desktop", $geoip_disable: true, $process_person_profile: false });
    const odd = analytics.catalogOptions.before_send({ uuid: "test", event: "visit_engaged", properties: {
      catalog_environment: "preview", seconds_to_engage: "soon", trigger: "typed some text" } });
    expect(sent && odd?.properties).toEqual({ catalog_environment: "preview", $geoip_disable: true, $process_person_profile: false });
    // The two labels belong to this event only.
    const pageview = analytics.catalogOptions.before_send({ uuid: "test", event: "$pageview", properties: {
      catalog_environment: "preview", page: "trending", seconds_to_engage: 17, trigger: "scroll" } });
    expect(pageview?.properties).not.toHaveProperty("trigger");
  } finally { done(); }
});

it("opts a browser out by address and remembers it until told otherwise", () => {
  window.localStorage.clear();
  expect(catalogOptedOut("")).toBe(false);
  expect(catalogOptedOut("?internal=1")).toBe(true);
  expect(catalogOptedOut("")).toBe(true);
  expect(catalogOptedOut("?utm_source=github")).toBe(true);
  expect(catalogOptedOut("?internal=0")).toBe(false);
  expect(catalogOptedOut("")).toBe(false);
  expect(catalogOptedOut("?internal=yes")).toBe(false);
});
