import { expect, it } from "vitest";
import { catalogOptions, catalogPage, catalogReferral, externalResource } from "./catalogAnalytics";
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
    vi.stubGlobal("navigator", {doNotTrack: "1"});
    catalogPageview("/catalog");
    expect(spy).toHaveBeenCalledTimes(2);
  } finally {
    window.history.replaceState({}, "", priorUrl);
    vi.restoreAllMocks(); vi.unstubAllEnvs(); vi.unstubAllGlobals();
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
