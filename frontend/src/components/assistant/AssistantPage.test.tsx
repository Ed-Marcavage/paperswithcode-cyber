import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { assistantApi, type AssistantConversation } from "@/lib/api/assistant";
import { AssistantProvider } from "./AssistantProvider";
import AssistantPage from "./AssistantPage";
import { ASSISTANT_PROMPTS } from "./prompts";

const saved: AssistantConversation = { id: "saved", title: "Old title", updated_at: "2026-11-14T12:00:00Z", question_count: 1, question_limit: 10,
  messages: [{ id: "a", role: "assistant", content: "Saved answer", status: "done", tool_steps: [] }] };
function mount(path = "/chat") {
  return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <MemoryRouter initialEntries={[path]}><AssistantProvider><Routes><Route path="/chat/:sessionId?" element={<AssistantPage />} /></Routes></AssistantProvider></MemoryRouter>
  </QueryClientProvider>);
}
beforeEach(() => { localStorage.clear(); vi.spyOn(assistantApi, "status").mockResolvedValue({ available: true, code: null, reason: null, retry_at: null }); vi.spyOn(assistantApi, "list").mockResolvedValue([saved]); vi.spyOn(assistantApi, "conversation").mockResolvedValue(saved); });
afterEach(() => vi.restoreAllMocks());
it("opens history by route, renames, confirms deletion and starts a new chat", async () => {
  const rename = vi.spyOn(assistantApi, "rename").mockResolvedValue({ ...saved, title: "New title" });
  const remove = vi.spyOn(assistantApi, "delete").mockResolvedValue();
  mount("/chat/saved");
  await screen.findByText("Saved answer");
  fireEvent.click(screen.getByRole("button", { name: "Rename chat" }));
  fireEvent.change(screen.getByLabelText("Chat title"), { target: { value: "New title" } });
  fireEvent.click(screen.getByRole("button", { name: "Save title" }));
  await waitFor(() => expect(rename).toHaveBeenCalledWith("saved", "New title"));
  fireEvent.click(screen.getByRole("button", { name: "Delete chat" }));
  expect(remove).not.toHaveBeenCalled();
  fireEvent.click(within(screen.getByRole("alertdialog")).getByText("Cancel"));
  expect(remove).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Delete chat" }));
  fireEvent.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Delete chat" }));
  await waitFor(() => expect(remove).toHaveBeenCalledWith("saved", expect.anything()));
  await screen.findByText(ASSISTANT_PROMPTS[0]);
  expect(screen.queryByText("Saved answer")).toBeNull();
  expect(localStorage.getItem("pwc:assistant:conversation")).toBeNull();
  expect(screen.queryByText("Clear chat")).toBeNull();
});
it("offers four prompts and lets the mobile history drawer close", async () => {
  mount();
  for (const prompt of ASSISTANT_PROMPTS) expect(screen.getByRole("button", { name: prompt })).toBeInTheDocument();
  fireEvent.click(screen.getByText(ASSISTANT_PROMPTS[2]));
  expect(screen.getByRole("textbox")).toHaveValue(ASSISTANT_PROMPTS[2]);
  fireEvent.click(screen.getByRole("button", { name: "Your chats" }));
  expect(screen.getByRole("button", { name: "Your chats" })).toHaveAttribute("aria-expanded", "true");
  fireEvent.click(screen.getByLabelText("Close chat list"));
  expect(screen.getByRole("button", { name: "Your chats" })).toHaveAttribute("aria-expanded", "false");
  await screen.findByText("Old title");
  fireEvent.click(screen.getByText("Old title"));
  await screen.findByText("Saved answer");
  fireEvent.click(screen.getByRole("button", { name: "New chat" }));
  await screen.findByText(ASSISTANT_PROMPTS[0]);
});
