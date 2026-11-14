import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { assistantApi, assistantKeys, AssistantError, type AssistantEvent } from "@/lib/api/assistant";
import { AssistantProvider } from "./AssistantProvider";
import { AssistantConversationView } from "./AssistantConversation";
import { AssistantLanding } from "./AssistantLanding";
const available = { available: true, code: null, reason: null, retry_at: null };
function mount(all = false) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><MemoryRouter><AssistantProvider>
    <AssistantConversationView />{all && <><AssistantConversationView surface="chat_page" /><AssistantLanding /></>}
  </AssistantProvider></MemoryRouter></QueryClientProvider>);
  return client;
}
async function ask(question = "My question") {
  const input = screen.getByRole("textbox");
  await waitFor(() => expect(input).toBeEnabled());
  fireEvent.change(input, { target: { value: question } }); fireEvent.click(screen.getByRole("button", { name: "Send" }));
}
beforeEach(() => { localStorage.clear(); vi.spyOn(assistantApi, "list").mockResolvedValue([]); vi.spyOn(assistantApi, "status").mockResolvedValue(available); });
afterEach(() => vi.restoreAllMocks());
it("preserves a failed question for retry and keeps partial output", async () => {
  const turn = vi.spyOn(assistantApi, "turn").mockImplementation(async function* (): AsyncGenerator<AssistantEvent> {
    yield { type: "text_delta", text: "Partial answer" };
    yield { type: "error", code: "provider_error", message: "The provider could not answer. Please try again." };
  });
  mount(); await ask();
  await screen.findByRole("button", { name: "Try again" });
  expect(screen.getByRole("textbox")).toHaveValue("My question");
  expect(screen.getByText("Partial answer")).toBeInTheDocument();
  turn.mockImplementation(async function* (): AsyncGenerator<AssistantEvent> { yield { type: "text_delta", text: "Retry answer" }; yield { type: "done", status: "done" }; });
  fireEvent.click(screen.getByRole("button", { name: "Try again" }));
  await screen.findByText("Retry answer"); expect(turn).toHaveBeenCalledTimes(2);
});
it("Stop aborts the request and leaves its answer visible", async () => {
  let aborted = false;
  vi.spyOn(assistantApi, "turn").mockImplementation(async function* (_q, _id, _s, _p, signal): AsyncGenerator<AssistantEvent> {
    yield { type: "text_delta", text: "Keep this" };
    await new Promise<void>((_resolve, reject) => signal.addEventListener("abort", () => { aborted = true; reject(new DOMException("Aborted", "AbortError")); }));
  });
  mount(); await ask(); await screen.findByText("Keep this");
  fireEvent.click(screen.getByRole("button", { name: "Stop" }));
  await screen.findByText("Stopped. Your partial answer is saved.");
  expect(aborted).toBe(true); expect(screen.getByText("Keep this")).toBeInTheDocument();
});
it("shares quota state across all three composers and automatically recovers", async () => {
  localStorage.setItem("pwc:assistant:conversation", "old");
  vi.spyOn(assistantApi, "conversation").mockResolvedValue({ id: "old", title: "Old", updated_at: "", question_count: 1, question_limit: 10,
    messages: [{ id: "a", role: "assistant", content: "Readable history", status: "done", tool_steps: [] }] });
  vi.mocked(assistantApi.status).mockResolvedValue({ available: false, code: "usage_limit", reason: "The assistant is resting.", retry_at: new Date(Date.now() + 200).toISOString() });
  mount(true);
  await screen.findAllByText("Readable history");
  await waitFor(() => expect(screen.getAllByRole("textbox").every(input => input.hasAttribute("disabled"))).toBe(true));
  for (const input of screen.getAllByRole("textbox")) expect(input).toHaveAttribute("placeholder", "The assistant is resting.");
  vi.mocked(assistantApi.status).mockResolvedValue(available);
  await waitFor(() => expect(screen.getAllByRole("textbox").every(input => !input.hasAttribute("disabled"))).toBe(true));
});
it("separates the ten-question limit from switched-off settings", async () => {
  // Admission can reject an outdated browser count after another tab sends.
  vi.spyOn(assistantApi, "turn").mockImplementation(() => { throw new AssistantError("This chat has reached 10 questions.", "question_limit", 409); });
  const client = mount(); await ask();
  await screen.findByRole("button", { name: "New chat" });
  expect(screen.getByRole("textbox")).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "New chat" }));
  expect(screen.getByRole("textbox")).toBeEnabled();
  act(() => client.setQueryData(assistantKeys.status, { available: false, code: "disabled", reason: "The assistant is switched off.", retry_at: null }));
  await screen.findByText("The assistant is switched off.");
  expect(screen.getByRole("textbox")).toBeDisabled();
});
