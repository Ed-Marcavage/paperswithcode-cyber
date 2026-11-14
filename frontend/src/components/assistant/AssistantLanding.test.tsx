import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { assistantApi, type AssistantEvent } from "@/lib/api/assistant";
import { AssistantProvider } from "./AssistantProvider";
import { AssistantLanding } from "./AssistantLanding";
import AssistantPage from "./AssistantPage";
import { ASSISTANT_PROMPTS } from "./prompts";
import { useRotatingPlaceholder } from "./useRotatingPlaceholder";
const available = { available: true, code: null, reason: null, retry_at: null };
function mount() {
  return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <MemoryRouter><AssistantProvider><Routes><Route path="/" element={<AssistantLanding />} /><Route path="/chat/:sessionId?" element={<AssistantPage />} /></Routes></AssistantProvider></MemoryRouter>
  </QueryClientProvider>);
}
beforeEach(() => { localStorage.clear(); vi.spyOn(assistantApi, "status").mockResolvedValue(available); vi.spyOn(assistantApi, "list").mockResolvedValue([]); });
afterEach(() => { vi.restoreAllMocks(); vi.useRealTimers(); });
it("accepts Tab and sends once from the landing box into a new chat", async () => {
  localStorage.setItem("pwc:assistant:conversation", "old");
  vi.spyOn(assistantApi, "conversation").mockResolvedValue({ id: "old", title: "Old", updated_at: "", question_count: 1, question_limit: 10, messages: [] });
  const turn = vi.spyOn(assistantApi, "turn").mockImplementation(async function* (): AsyncGenerator<AssistantEvent> {
    yield { type: "meta", conversation_id: "new", message_id: "a", run_id: "r", question_count: 1, question_limit: 10 };
    yield { type: "text_delta", text: "New answer" }; yield { type: "done", status: "done" };
  });
  mount();
  const input = screen.getByLabelText("Ask the catalog");
  await waitFor(() => expect(input).toBeEnabled());
  fireEvent.keyDown(input, { key: "Tab" });
  expect(input).toHaveValue(ASSISTANT_PROMPTS[0]);
  fireEvent.keyDown(input, { key: "Enter" });
  await screen.findByText("New answer");
  expect(turn).toHaveBeenCalledTimes(1);
  expect(turn).toHaveBeenCalledWith(ASSISTANT_PROMPTS[0], null, "landing", "/", expect.any(AbortSignal));
});
it("disables the box and uses the same status reason for placeholder and hover", async () => {
  vi.mocked(assistantApi.status).mockResolvedValue({ available: false, code: "usage_limit", reason: "The assistant is resting.", retry_at: "2099-01-01T00:00:00Z" });
  mount();
  const input = await screen.findByPlaceholderText("The assistant is resting.");
  expect(input).toBeDisabled(); expect(input).toHaveAttribute("title", "The assistant is resting.");
});
function Animation() { const { placeholder, prompt } = useRotatingPlaceholder(true); return <div data-testid="animation" data-prompt={prompt}>{placeholder}</div>; }
it("cycles prompts in fixed order and stays static with reduced motion", () => {
  vi.useFakeTimers();
  const media = vi.spyOn(window, "matchMedia").mockReturnValue({ matches: false } as MediaQueryList);
  const view = render(<Animation />);
  for (let i = 1; i < 5; i++) {
    const previous = ASSISTANT_PROMPTS[(i - 1) % 4];
    const duration = (previous.length - 1) * 45 + 1800 + (previous.length - 1) * 25;
    act(() => { vi.advanceTimersByTime(duration + (i === 1 ? 0 : 395)); });
    expect(screen.getByTestId("animation")).toHaveAttribute("data-prompt", ASSISTANT_PROMPTS[i % 4]);
  }
  view.unmount(); media.mockReturnValue({ matches: true } as MediaQueryList);
  render(<Animation />);
  act(() => { vi.advanceTimersByTime(60_000); });
  expect(screen.getByTestId("animation")).toHaveTextContent(ASSISTANT_PROMPTS[0]);
});
