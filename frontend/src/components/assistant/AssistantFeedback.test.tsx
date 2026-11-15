import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, it, vi } from "vitest";
import { assistantApi } from "@/lib/api/assistant";
import * as analytics from "@/lib/catalogAnalytics";
import { AssistantFeedback } from "./AssistantFeedback";
afterEach(() => vi.restoreAllMocks());
const message = { id: "a", run_id: "run-id", role: "assistant" as const, status: "done", content: "answer", tool_steps: [] };
function mount() {
  return render(<QueryClientProvider client={new QueryClient()}><AssistantFeedback message={message} /></QueryClientProvider>);
}
it("saves a thumb at once, then an optional note on the same run, preserving the note on error", async () => {
  const event = vi.spyOn(analytics, "assistantEvent").mockImplementation(() => {});
  const save = vi.spyOn(assistantApi, "feedback").mockResolvedValueOnce({ saved: true }).mockRejectedValueOnce(new Error("Failed")).mockResolvedValue({ saved: true });
  mount();
  expect(screen.queryByLabelText("Optional note")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Bad answer" }));
  expect(screen.getByRole("button", { name: "Bad answer" })).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByRole("button", { name: "Good answer" })).toHaveAttribute("aria-pressed", "false");
  await screen.findByText("Thanks for the feedback.");
  expect(save).toHaveBeenLastCalledWith("run-id", "bad", "");
  expect(event).toHaveBeenLastCalledWith("feedback_given", "panel");
  fireEvent.change(screen.getByLabelText("Optional note"), { target: { value: "Missed a source" } });
  fireEvent.click(screen.getByRole("button", { name: "Send note" }));
  await screen.findByRole("alert"); expect(screen.getByLabelText("Optional note")).toHaveValue("Missed a source");
  expect(screen.getByLabelText("Optional note")).toHaveAttribute("maxlength", "500");
  fireEvent.click(screen.getByRole("button", { name: "Send note" }));
  await screen.findByText("Thanks for the feedback."); expect(save).toHaveBeenLastCalledWith("run-id", "bad", "Missed a source");
  await waitFor(() => expect(screen.queryByLabelText("Optional note")).toBeNull());
  expect(event).toHaveBeenCalledTimes(2);
});
it("shows a saved rating as pressed and hides controls while the answer runs", () => {
  const { rerender } = render(<QueryClientProvider client={new QueryClient()}>
    <AssistantFeedback message={{ ...message, feedback: { rating: "good", note: null } }} /></QueryClientProvider>);
  expect(screen.getByRole("button", { name: "Good answer" })).toHaveAttribute("aria-pressed", "true");
  rerender(<QueryClientProvider client={new QueryClient()}><AssistantFeedback message={{ ...message, status: "running" }} /></QueryClientProvider>);
  expect(screen.queryByRole("button", { name: "Good answer" })).toBeNull();
});
