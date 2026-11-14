import { fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, it, vi } from "vitest";
import { assistantApi } from "@/lib/api/assistant";
import { AssistantFeedback } from "./AssistantFeedback";
afterEach(() => vi.restoreAllMocks());
it("saves a rating and optional note on the answer's run, preserving the note on error", async () => {
  const save = vi.spyOn(assistantApi, "feedback").mockRejectedValueOnce(new Error("Failed")).mockResolvedValue({ saved: true });
  render(<QueryClientProvider client={new QueryClient()}><AssistantFeedback message={{ id: "a", run_id: "run-id", role: "assistant", status: "done", content: "answer", tool_steps: [] }} /></QueryClientProvider>);
  fireEvent.click(screen.getByText("Give feedback"));
  fireEvent.click(screen.getByRole("button", { name: "Bad answer" }));
  fireEvent.change(screen.getByLabelText("Optional note"), { target: { value: "Missed a source" } });
  fireEvent.click(screen.getByRole("button", { name: "Save feedback" }));
  await screen.findByRole("alert"); expect(screen.getByLabelText("Optional note")).toHaveValue("Missed a source");
  fireEvent.click(screen.getByRole("button", { name: "Save feedback" }));
  await screen.findByText("Feedback saved."); expect(save).toHaveBeenLastCalledWith("run-id", "bad", "Missed a source");
  expect(screen.getByLabelText("Optional note")).toHaveAttribute("maxlength", "500");
});
