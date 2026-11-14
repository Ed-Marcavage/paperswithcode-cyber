import { afterEach, describe, expect, it, vi } from "vitest";
import { assistantApi, AssistantError } from "./assistant";

afterEach(() => vi.unstubAllGlobals());
describe("assistant transport", () => {
  it("parses split UTF-8 SSE frames and sends no visitor or analytics identity", async () => {
    const bytes = new TextEncoder().encode('event: text_delta\r\ndata: {"type":"text_delta","text":"🦊"}\r\n\r\nevent: done\ndata: {"type":"done","status":"done"}\n\n');
    const stream = new ReadableStream<Uint8Array>({ start(controller) {
      for (const byte of bytes) controller.enqueue(Uint8Array.of(byte));
      controller.close();
    } });
    const fetch = vi.fn().mockResolvedValue(new Response(stream));
    vi.stubGlobal("fetch", fetch);
    const events = [];
    for await (const event of assistantApi.turn("Question", null, "panel", "/catalog", new AbortController().signal)) events.push(event);
    expect(events).toEqual([{ type: "text_delta", text: "🦊" }, { type: "done", status: "done" }]);
    expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({ question: "Question", conversation_id: null, surface: "panel", site_path: "/catalog" });
    expect(fetch.mock.calls[0][1].credentials).toBe("same-origin");
  });
  it("preserves quota reason and reset on a rejected turn", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: {
      code: "usage_limit", reason: "Resting", retry_at: "2026-11-15T00:00:00Z",
    } }), { status: 503 })));
    const events = assistantApi.turn("Question", null, "panel", "/", new AbortController().signal);
    await expect(events.next()).rejects.toMatchObject({ code: "usage_limit", message: "Resting", retryAt: "2026-11-15T00:00:00Z" });
  });
  it("does not call a truncated stream complete", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response('data: {"type":"text_delta","text":"partial"}\n\n')));
    const events = assistantApi.turn("Question", null, "panel", "/", new AbortController().signal);
    expect((await events.next()).value).toEqual({ type: "text_delta", text: "partial" });
    await expect(events.next()).rejects.toBeInstanceOf(AssistantError);
  });
});
