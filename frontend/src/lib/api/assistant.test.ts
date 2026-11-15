import { afterEach, describe, expect, it, vi } from "vitest";
import { assistantApi, AssistantError, followUps } from "./assistant";

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


it("preserves working-note events separately from answer deltas", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(
    'data: {"type":"working_note","text":"Checking posts"}\n\n' +
    'data: {"type":"text_delta","text":"Answer"}\n\n' +
    'data: {"type":"done","status":"done"}\n\n',
  )));
  const events = [];
  for await (const event of assistantApi.turn("Question", null, "panel", "/", new AbortController().signal)) events.push(event);
  expect(events).toEqual([
    { type: "working_note", text: "Checking posts" },
    { type: "text_delta", text: "Answer" },
    { type: "done", status: "done" },
  ]);
});

describe("topics and follow-ups", () => {
  it("fetches topics in the order returned and drops malformed entries", async () => {
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ topics: [
      { slug: "vulnerability-analysis", label: "Vulnerability detection and triage", count: 169 },
      { slug: "penetration-testing", label: "Penetration testing", count: 107 },
      { slug: "", label: "Nameless", count: 3 }, { label: "No slug", count: 1 }, null,
    ] })));
    vi.stubGlobal("fetch", fetch);
    expect(await assistantApi.topics()).toEqual([
      { slug: "vulnerability-analysis", label: "Vulnerability detection and triage", count: 169 },
      { slug: "penetration-testing", label: "Penetration testing", count: 107 },
    ]);
    expect(String(fetch.mock.calls[0][0])).toContain("/api/v1/assistant/topics");
  });
  it.each([
    ["a server error", () => Promise.resolve(new Response("{}", { status: 500 }))],
    ["a network failure", () => Promise.reject(new TypeError("offline"))],
    ["an unexpected body", () => Promise.resolve(new Response(JSON.stringify({ items: [] })))],
    ["an empty list", () => Promise.resolve(new Response(JSON.stringify({ topics: [] })))],
  ])("returns no topics on %s", async (_case, respond) => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation(respond));
    expect(await assistantApi.topics()).toEqual([]);
  });
  it("sends the topic in the turn body only when one is chosen, and passes follow-ups through", async () => {
    const fetch = vi.fn().mockImplementation(() => Promise.resolve(new Response('data: {"type":"done","status":"done","follow_ups":["Next?"]}\n\n')));
    vi.stubGlobal("fetch", fetch);
    const events = [];
    for await (const event of assistantApi.turn("Question", "c1", "chat_page", "/chat", new AbortController().signal, "fuzzing")) events.push(event);
    expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({ question: "Question", conversation_id: "c1", surface: "chat_page", site_path: "/chat", topic: "fuzzing" });
    expect(events).toEqual([{ type: "done", status: "done", follow_ups: ["Next?"] }]);
    for await (const _event of assistantApi.turn("Question", "c1", "chat_page", "/chat", new AbortController().signal, null)) { /* drain */ }
    expect(JSON.parse(fetch.mock.calls[1][1].body)).not.toHaveProperty("topic");
  });
  it("reads absent or odd follow-ups as none and keeps at most three", () => {
    expect(followUps(undefined)).toEqual([]);
    expect(followUps("Next?")).toEqual([]);
    expect(followUps(["One", "", 3, "Two", "Three", "Four"])).toEqual(["One", "Two", "Three"]);
  });
});

it("passes answer_complete through and keeps reading until done", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(
    'data: {"type":"text_delta","text":"Answer"}\n\ndata: {"type":"answer_complete"}\n\ndata: {"type":"done","status":"done","follow_ups":[]}\n\n')));
  const events = [];
  for await (const event of assistantApi.turn("Question", null, "panel", "/", new AbortController().signal)) events.push(event);
  expect(events.map(event => event.type)).toEqual(["text_delta", "answer_complete", "done"]);
});
