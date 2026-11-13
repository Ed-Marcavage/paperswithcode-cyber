import { expect, it } from "vitest";
import { catalogOptions, catalogPage, catalogReferral, catalogReferrerDomain, externalResource } from "./catalogAnalytics";
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
