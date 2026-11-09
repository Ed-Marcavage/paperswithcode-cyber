import { expect, it } from "vitest";
import { catalogOptions, catalogPage, externalResource } from "./catalogAnalytics";
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
