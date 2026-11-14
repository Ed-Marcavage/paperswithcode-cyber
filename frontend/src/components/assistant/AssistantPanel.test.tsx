import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Link, MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { assistantApi, type AssistantConversation, type AssistantEvent } from "@/lib/api/assistant";
import { isAssistantEnabled } from "@/lib/apiUrl";
import { AssistantProvider } from "./AssistantProvider";
import { AssistantAskButton, AssistantPanel } from "./AssistantPanel";

function mount() {
  return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <MemoryRouter><AssistantProvider><AssistantAskButton /><Link to="/catalog">Browse</Link>
      <Routes><Route path="/" element={<p>Home page</p>} /><Route path="/catalog" element={<p>Catalog page</p>} /></Routes>
      <AssistantPanel /></AssistantProvider></MemoryRouter>
  </QueryClientProvider>);
}
beforeEach(() => { localStorage.clear(); vi.spyOn(assistantApi, "list").mockResolvedValue([]); });
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllEnvs(); });

it("keeps an active stream through navigation, panel close and reopen", async () => {
  let finish!: () => void;
  const gate = new Promise<void>(resolve => { finish = resolve; });
  let signal: AbortSignal | undefined;
  vi.spyOn(assistantApi, "turn").mockImplementation(async function* (_q, _id, _surface, _path, inputSignal): AsyncGenerator<AssistantEvent> {
    signal = inputSignal;
    yield { type: "meta", conversation_id: "saved", message_id: "answer", run_id: "run", question_count: 1, question_limit: 10 };
    yield { type: "text_delta", text: "First" };
    await gate;
    yield { type: "text_delta", text: " and second" };
    yield { type: "done", status: "done" };
  });
  mount();
  fireEvent.click(screen.getByRole("button", { name: "Ask" }));
  const input = screen.getByRole("textbox", { name: "Your question" });
  expect(input).toHaveFocus();
  fireEvent.change(input, { target: { value: "Find research" } });
  fireEvent.keyDown(input, { key: "Enter" });
  await screen.findByText("First");
  fireEvent.click(screen.getByText("Browse"));
  expect(screen.getByText("Catalog page")).toBeInTheDocument();
  expect(screen.getByText("First")).toBeInTheDocument();
  fireEvent.keyDown(document, { key: "Escape" });
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Ask" })).toHaveFocus();
  expect(signal?.aborted).toBe(false);
  fireEvent.click(screen.getByRole("button", { name: "Ask" }));
  await act(async () => { finish(); });
  await screen.findByText("First and second");
  expect(localStorage.getItem("pwc:assistant:conversation")).toBe("saved");
  expect(localStorage.getItem("pwc:assistant:open")).toBe("true");
  expect(assistantApi.turn).toHaveBeenCalledTimes(1);
});

it("restores the browser conversation and shows count and character budget", async () => {
  localStorage.setItem("pwc:assistant:open", "true");
  localStorage.setItem("pwc:assistant:conversation", "restored");
  const restored: AssistantConversation = { id: "restored", title: "Research", updated_at: "", question_count: 2, question_limit: 10,
    messages: [{ id: "old", role: "assistant", content: "Saved answer", status: "done", tool_steps: [] }] };
  vi.spyOn(assistantApi, "conversation").mockResolvedValue(restored);
  mount();
  await screen.findByText("Saved answer");
  expect(screen.getByText("Question 3 of 10")).toBeInTheDocument();
  const input = screen.getByRole("textbox");
  fireEvent.change(input, { target: { value: "x".repeat(850) } });
  expect(screen.getByText("850/1000")).toBeInTheDocument();
  const send = vi.spyOn(assistantApi, "turn");
  fireEvent.keyDown(input, { key: "Enter", shiftKey: true });
  await waitFor(() => expect(send).not.toHaveBeenCalled());
  expect(input).toHaveAttribute("maxlength", "1000");
});

it("uses its own build flag even with the local catalog enabled", () => {
  vi.stubEnv("VITE_CHAT_ENABLED", "false"); vi.stubEnv("VITE_LOCAL_CATALOG", "true");
  vi.stubEnv("VITE_ASSISTANT_ENABLED", "true"); expect(isAssistantEnabled()).toBe(true);
  vi.stubEnv("VITE_ASSISTANT_ENABLED", "false"); expect(isAssistantEnabled()).toBe(false);
});
