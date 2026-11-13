import type { PostHogConfig } from "posthog-js";

export const posthogPrivacyOptions = {
  api_host: import.meta.env.VITE_POSTHOG_HOST,
  defaults: "2026-05-30",
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
} satisfies Partial<PostHogConfig>;

/** A page address as recordings keep it: origin and path, without query string or fragment. */
export function replayUrl(url: string): string | null {
  try {
    const parsed = new URL(url);
    return parsed.origin + parsed.pathname;
  } catch {
    return null;
  }
}

/**
 * Session replay settings for the catalog build. Page text is public catalog
 * content and is recorded; every input's value is masked, and text that echoes
 * a search (marked `ph-mask` in the components) is masked too. Account UI
 * cannot render in the catalog build (auth is off), but is blocked in case it
 * ever does. No canvas, cross-origin iframes, headers or bodies; recorded page
 * addresses lose their query string and fragment.
 */
export const catalogRecordingOptions = {
  maskAllInputs: true,
  maskInputOptions: { password: true },
  blockSelector: ".user-avatar-btn, .settings-page-content, .following-topic-note",
  recordCrossOriginIframes: false,
  recordHeaders: false,
  recordBody: false,
  captureCanvas: { recordCanvas: false },
  maskCapturedNetworkRequestFn: request => ({ ...request, name: replayUrl(request.name) ?? "" }),
} satisfies PostHogConfig["session_recording"];
