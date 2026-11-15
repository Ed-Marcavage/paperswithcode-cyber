import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import posthog from "posthog-js";
import { afterEach, expect, it, vi } from "vitest";
import { assistantEvent, catalogOptions } from "@/lib/catalogAnalytics";
import PrivacyView from "@/views/PrivacyView";
import { AssistantProvider } from "./AssistantProvider";
import { AssistantConversationView } from "./AssistantConversation";
import { assistantApi, type AssistantEvent } from "@/lib/api/assistant";
const actions = ["opened", "asked_from_landing", "message_sent", "answer_done", "link_clicked", "new_chat", "feedback_given", "limit_hit", "error"] as const;
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllEnvs(); vi.unstubAllGlobals(); localStorage.clear(); });
it("allows nine events with fixed surfaces and strips all conversation and URL properties", () => {
  for (const action of actions) {
    const sent = catalogOptions.before_send({ uuid: "test", event: `assistant_${action}`, properties: {
      catalog_environment: "preview", surface: "panel", question: "private", answer: "private", note: "private", title: "private", paper_title: "private",
      value: "private", conversation_id: "private", run_id: "private", href: "private", $current_url: "private", $set: { text: "private" },
    } });
    expect(sent?.properties).toEqual({ catalog_environment: "preview", surface: "panel", $geoip_disable: true, $process_person_profile: false });
  }
  expect(catalogOptions.before_send({ uuid: "test", event: "assistant_error", properties: { catalog_environment: "preview", surface: "private" } })).toBeNull();
});
it("honors DNT and GPC for every assistant event", () => {
  const capture = vi.spyOn(posthog, "capture").mockReturnValue(undefined);
  vi.stubEnv("VITE_LOCAL_CATALOG", "true"); vi.stubEnv("VITE_POSTHOG_PROJECT_TOKEN", "phc_test");
  for (const action of actions) assistantEvent(action, "panel");
  expect(capture).toHaveBeenCalledTimes(9);
  for (const privacy of [{ doNotTrack: "1" }, { globalPrivacyControl: true }]) {
    vi.stubGlobal("navigator", privacy);
    for (const action of actions) assistantEvent(action, "landing");
  }
  expect(capture).toHaveBeenCalledTimes(9);
});
it("masks transcript and composer while actual sent and done events contain no text", async () => {
  vi.stubEnv("VITE_LOCAL_CATALOG", "true"); vi.stubEnv("VITE_POSTHOG_PROJECT_TOKEN", "phc_test");
  const capture = vi.spyOn(posthog, "capture").mockReturnValue(undefined);
  vi.spyOn(assistantApi, "status").mockResolvedValue({ available: true, code: null, reason: null, retry_at: null });
  vi.spyOn(assistantApi, "list").mockResolvedValue([]);
  vi.spyOn(assistantApi, "turn").mockImplementation(async function* (): AsyncGenerator<AssistantEvent> {
    yield { type: "text_delta", text: "Private answer" }; yield { type: "done", status: "done" };
  });
  render(<QueryClientProvider client={new QueryClient()}><MemoryRouter><AssistantProvider><AssistantConversationView /></AssistantProvider></MemoryRouter></QueryClientProvider>);
  const input = screen.getByRole("textbox"); await waitFor(() => expect(input).toBeEnabled());
  expect(input.closest(".ph-mask")).not.toBeNull();
  fireEvent.change(input, { target: { value: "Private question" } }); fireEvent.click(screen.getByRole("button", { name: "Send" }));
  expect((await screen.findByText("Private answer")).closest(".ph-mask")).not.toBeNull();
  expect(capture).toHaveBeenCalledWith("assistant_message_sent", { surface: "panel", chat: "new", catalog_environment: "preview" });
  expect(capture).toHaveBeenCalledWith("assistant_answer_done", { surface: "panel", catalog_environment: "preview" });
  expect(JSON.stringify(capture.mock.calls)).not.toContain("Private");
});
it("discloses last-activity retention, Ollama processing, deletion and saved DNT history", () => {
  vi.stubEnv("VITE_LOCAL_CATALOG", "true"); render(<PrivacyView />);
  expect(screen.getByText(/we store your chat text/)).toHaveTextContent(/tool steps.*feedback.*random browser identifier/);
  expect(screen.getByText(/Ollama processes/)).toHaveTextContent(/90 days after the conversation’s last activity/);
  expect(screen.getByText(/Ollama processes/)).toHaveTextContent(/All chats.*Delete.*confirm/);
  expect(screen.getByText(/The transcript, composer/)).toHaveTextContent(/PostHog session id is not stored.*still saves chats/);
  // What assistant analytics does carry: the topic, the link kind and the thumb, never text.
  expect(screen.getByText(/The transcript, composer/)).toHaveTextContent(/choosing a topic.*stays on this site.*thumbs up or down.*never includes chat text/);
  expect(screen.getByText(/We also record sessions/)).toHaveTextContent(/follow-up questions and chat titles are replaced with asterisks.*links inside answers are left out/);
});
