import { describe, expect, it } from "vitest";

import { catalogRecordingOptions, posthogPrivacyOptions, replayUrl } from "./posthogPrivacy";

describe("PostHog privacy initialization", () => {
  it("keeps pageviews while disabling automatic collection and remote reconfiguration", () => {
    expect(posthogPrivacyOptions).toMatchObject({
      autocapture: false,
      rageclick: false,
      capture_dead_clicks: false,
      capture_exceptions: false,
      capture_pageleave: false,
      capture_pageview: true,
      capture_performance: false,
      disable_session_recording: true,
      advanced_disable_flags: true,
      disable_external_dependency_loading: true,
      mask_all_text: true,
      mask_all_element_attributes: true,
    });
  });

  it("records catalog sessions with every input masked and no canvas, iframes, headers or bodies", () => {
    expect(catalogRecordingOptions).toMatchObject({
      maskAllInputs: true,
      recordCrossOriginIframes: false,
      recordHeaders: false,
      recordBody: false,
      captureCanvas: { recordCanvas: false },
    });
    expect(catalogRecordingOptions.blockSelector).toContain(".user-avatar-btn");
  });

  it("keeps only the origin and path of recorded page addresses", () => {
    expect(replayUrl("https://catalog.example/papers?search=private#top")).toBe("https://catalog.example/papers");
    expect(replayUrl("not a url")).toBeNull();
    const masked = catalogRecordingOptions.maskCapturedNetworkRequestFn({ name: "https://catalog.example/catalog?topic=fuzzing" } as never);
    expect(masked?.name).toBe("https://catalog.example/catalog");
  });
});
