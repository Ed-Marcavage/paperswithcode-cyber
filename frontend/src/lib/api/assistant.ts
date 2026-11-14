import { apiUrl } from "@/lib/apiUrl";

export type AssistantSurface = "landing" | "panel" | "chat_page";
export interface AssistantStatus { available: boolean; code: string | null; reason: string | null; retry_at: string | null }
export interface AssistantToolStep { name: string; call_id?: string; result?: string; error?: string | boolean | null; pending?: boolean }
export interface AssistantMessage {
  id: string; role: "user" | "assistant"; content: string; status: string;
  tool_steps: AssistantToolStep[]; run_id?: string | null; error?: string | null;
  feedback?: { rating: "good" | "bad" | null; note: string | null } | null;
}
export interface AssistantSummary { id: string; title: string; updated_at: string; question_count: number; question_limit: number }
export interface AssistantConversation extends AssistantSummary { messages: AssistantMessage[] }
export type AssistantEvent =
  | { type: "meta"; conversation_id: string; message_id: string; run_id: string; question_count: number; question_limit: number }
  | { type: "text_delta"; text: string }
  | { type: "tool_started" | "tool_finished"; id: string; name: string; error?: boolean }
  | { type: "done"; status: string }
  | { type: "error"; code: string; message: string; retry_at?: string | null };

export class AssistantError extends Error {
  constructor(message: string, public code = "provider_error", public status = 0, public retryAt: string | null = null) {
    super(message);
  }
}

const root = "/api/v1/assistant";
async function check(response: Response) {
  if (response.ok) return;
  const body = await response.json().catch(() => ({})) as {
    detail?: string | { code?: string; message?: string; reason?: string; retry_at?: string };
  };
  const detail = body.detail;
  const message = typeof detail === "string" ? detail : detail?.reason || detail?.message;
  throw new AssistantError(message || "The assistant could not respond. Please try again.",
    typeof detail === "object" ? detail?.code : response.status === 404 ? "disabled" : undefined,
    response.status, typeof detail === "object" ? detail?.retry_at : null);
}
async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(apiUrl(root + path), { credentials: "same-origin", ...options });
  await check(response);
  return response.status === 204 ? undefined as T : response.json() as Promise<T>;
}
function json(method: string, body: unknown): RequestInit {
  return { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
}

async function* turn(question: string, conversationId: string | null, surface: AssistantSurface, sitePath: string, signal: AbortSignal): AsyncGenerator<AssistantEvent> {
  const response = await fetch(apiUrl(root + "/turn"), { ...json("POST", {
    question, conversation_id: conversationId, surface, site_path: sitePath,
  }), credentials: "same-origin", signal });
  await check(response);
  if (!response.body) throw new AssistantError("The answer stream could not start. Please try again.");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      buffer = buffer.replace(/\r\n/g, "\n");
      let end: number;
      while ((end = buffer.indexOf("\n\n")) >= 0) {
        const frame = buffer.slice(0, end);
        buffer = buffer.slice(end + 2);
        const data = frame.split("\n").filter(line => line.startsWith("data:")).map(line => line.slice(5).trimStart()).join("\n");
        if (!data) continue;
        const event = JSON.parse(data) as AssistantEvent;
        yield event;
        if (event.type === "done" || event.type === "error") return;
      }
      if (done) throw new AssistantError("The answer was interrupted. Please try again.");
    }
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}

export const assistantApi = {
  list: () => request<AssistantSummary[]>("/conversations"),
  conversation: (id: string) => request<AssistantConversation>(`/conversations/${encodeURIComponent(id)}`),
  rename: (id: string, title: string) => request<AssistantSummary>(`/conversations/${encodeURIComponent(id)}`, json("PATCH", { title })),
  delete: (id: string) => request<void>(`/conversations/${encodeURIComponent(id)}`, { method: "DELETE" }),
  feedback: (runId: string, rating: "good" | "bad", note: string) => request<{ saved: boolean }>(`/runs/${encodeURIComponent(runId)}/feedback`, json("POST", { rating, note })),
  status: async (): Promise<AssistantStatus> => {
    try { return await request<AssistantStatus>("/status"); }
    catch (error) {
      if (error instanceof AssistantError && [404, 503].includes(error.status)) {
        return { available: false, code: error.status === 404 ? "disabled" : "not_configured",
          reason: error.status === 404 ? "The assistant is switched off." : error.message, retry_at: null };
      }
      throw error;
    }
  },
  turn,
};

export const assistantKeys = {
  list: ["assistant", "conversations"] as const,
  conversation: (id: string) => ["assistant", "conversation", id] as const,
  status: ["assistant", "status"] as const,
};
