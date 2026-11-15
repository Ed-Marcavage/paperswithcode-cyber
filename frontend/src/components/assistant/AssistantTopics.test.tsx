import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import posthog from "posthog-js";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { assistantApi, type AssistantEvent, type AssistantTopic } from "@/lib/api/assistant";
import { assistantEvent, catalogOptions } from "@/lib/catalogAnalytics";
import { AssistantProvider } from "./AssistantProvider";
import { AssistantConversationView } from "./AssistantConversation";
import { AssistantLanding } from "./AssistantLanding";
import { AssistantAskButton, AssistantPanel } from "./AssistantPanel";
import AssistantPage from "./AssistantPage";
import { ASSISTANT_PROMPTS } from "./prompts";

const TOPICS: AssistantTopic[] = [
  { slug: "vulnerability-analysis", label: "Vulnerability detection and triage", count: 169 },
  { slug: "ai-system-security", label: "AI-system security", count: 144 },
  { slug: "penetration-testing", label: "Penetration testing", count: 107 },
  { slug: "repair", label: "Vulnerability repair", count: 34 },
  { slug: "fuzzing", label: "Fuzzing", count: 24 },
];
const available = { available: true, code: null, reason: null, retry_at: null };
function mount(node = <AssistantConversationView surface="chat_page" />, path = "/") {
  return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <MemoryRouter initialEntries={[path]}><AssistantProvider>{node}</AssistantProvider></MemoryRouter>
  </QueryClientProvider>);
}
function answering(events: AssistantEvent[] = [{ type: "text_delta", text: "Answer" }, { type: "done", status: "done" }]) {
  return vi.spyOn(assistantApi, "turn").mockImplementation(async function* (): AsyncGenerator<AssistantEvent> {
    yield { type: "meta", conversation_id: "new", message_id: "m", run_id: "run", question_count: 1, question_limit: 10 };
    for (const event of events) yield event;
  });
}
async function box() {
  const input = screen.getByRole("textbox", { name: "Your question" });
  await waitFor(() => expect(input).toBeEnabled());
  return input;
}
const chip = (name: string) => screen.getByRole("button", { name: new RegExp(`^${name}\\s*,`) });

beforeEach(() => {
  localStorage.clear();
  vi.spyOn(assistantApi, "status").mockResolvedValue(available);
  vi.spyOn(assistantApi, "list").mockResolvedValue([]);
  vi.spyOn(assistantApi, "topics").mockResolvedValue(TOPICS);
});
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllEnvs(); vi.unstubAllGlobals(); });

describe("topic chips", () => {
  it("shows one chip per topic in order, and selects, switches and removes without sending", async () => {
    const turn = answering();
    mount();
    const input = await box();
    await screen.findByText("Or pick a topic, then ask your own question");
    const chips = within(screen.getByRole("group", { name: /Or pick a topic/ })).getAllByRole("button");
    expect(chips.map(button => button.textContent)).toEqual(TOPICS.map(topic => `${topic.label}${topic.count}, ${topic.count} entries`));
    expect(input).toHaveAttribute("placeholder", "Ask about the catalog, or type / for topics");

    fireEvent.click(chip("Penetration testing"));
    expect(chip("Penetration testing")).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("Penetration testing", { selector: ".assistant-topic-tag-label" })).toBeInTheDocument();
    expect(input).toHaveFocus();
    expect(input).toHaveAttribute("placeholder", "Ask about penetration testing…");

    fireEvent.click(chip("AI-system security"));
    expect(chip("Penetration testing")).toHaveAttribute("aria-pressed", "false");
    expect(input).toHaveAttribute("placeholder", "Ask about AI-system security…");

    fireEvent.click(chip("AI-system security"));
    expect(screen.queryByRole("button", { name: /Remove topic/ })).not.toBeInTheDocument();
    fireEvent.click(chip("Fuzzing"));
    fireEvent.click(screen.getByRole("button", { name: "Remove topic Fuzzing" }));
    expect(chip("Fuzzing")).toHaveAttribute("aria-pressed", "false");
    expect(input).toHaveAttribute("placeholder", "Ask about the catalog, or type / for topics");
    expect(turn).not.toHaveBeenCalled();
  });

  it("sends the topic with the visitor's own question, labels the question and keeps the topic for the chat", async () => {
    const turn = answering();
    mount();
    const input = await box();
    await screen.findByText(/Or pick a topic/);
    fireEvent.click(chip("Penetration testing"));
    fireEvent.change(input, { target: { value: "Which harnesses chain recon and exploitation?" } });
    fireEvent.keyDown(input, { key: "Enter" });
    await screen.findByText("Answer");
    expect(turn).toHaveBeenCalledWith("Which harnesses chain recon and exploitation?", null, "chat_page", "/", expect.any(AbortSignal), "penetration-testing");
    expect(screen.getByText("Topic: Penetration testing")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Remove topic Penetration testing" })).toBeInTheDocument();
    expect(input).toHaveAttribute("placeholder", "Ask a follow-up about penetration testing…");
    fireEvent.change(input, { target: { value: "And which publish code?" } });
    fireEvent.keyDown(input, { key: "Enter" });
    await waitFor(() => expect(turn).toHaveBeenCalledTimes(2));
    expect(turn).toHaveBeenLastCalledWith("And which publish code?", "new", "chat_page", "/", expect.any(AbortSignal), "penetration-testing");
    expect(localStorage.getItem("pwc:assistant:topic")).toBeNull();
    expect(JSON.stringify(localStorage)).not.toContain("penetration");
  });

  it("lets the example questions send without a topic", async () => {
    const turn = answering();
    mount();
    const input = await box();
    await screen.findByText(/Or pick a topic/);
    fireEvent.click(chip("Fuzzing"));
    fireEvent.click(screen.getByRole("button", { name: ASSISTANT_PROMPTS[1] }));
    expect(input).toHaveValue(ASSISTANT_PROMPTS[1]);
    expect(screen.queryByRole("button", { name: /Remove topic/ })).not.toBeInTheDocument();
    fireEvent.keyDown(input, { key: "Enter" });
    await screen.findByText("Answer");
    expect(turn).toHaveBeenCalledWith(ASSISTANT_PROMPTS[1], null, "chat_page", "/", expect.any(AbortSignal));
  });

  it("leaves the topic UI out when the endpoint fails or is empty, and everything else works", async () => {
    vi.mocked(assistantApi.topics).mockResolvedValue([]);
    const turn = answering();
    mount();
    const input = await box();
    expect(screen.getByRole("button", { name: ASSISTANT_PROMPTS[0] })).toBeInTheDocument();
    expect(screen.queryByText(/Or pick a topic/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Topics" })).not.toBeInTheDocument();
    expect(input).toHaveAttribute("placeholder", "Ask about the catalog…");
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: "/etc" } });
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    fireEvent.keyDown(input, { key: "Enter" });
    await waitFor(() => expect(turn).toHaveBeenCalledWith("/etc", null, "chat_page", "/", expect.any(AbortSignal)));
  });
});

describe("slash command list", () => {
  async function slash(text: string) {
    const input = await box();
    await screen.findByText(/Or pick a topic/);
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: text } });
    return input;
  }

  it("opens on a leading slash as an announced listbox the textarea points into, and filters by label", async () => {
    mount();
    const input = await slash("/");
    const list = screen.getByRole("listbox", { name: "Commands" });
    expect(within(list).getByRole("group", { name: "Topics" })).toBeInTheDocument();
    expect(within(list).getAllByRole("option")).toHaveLength(5);
    expect(input).toHaveAttribute("aria-controls", list.id);
    expect(input).toHaveAttribute("aria-autocomplete", "list");
    const first = within(list).getAllByRole("option")[0];
    expect(input).toHaveAttribute("aria-activedescendant", first.id);
    expect(first).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("status", { name: "" })).toHaveTextContent("5 topics");

    fireEvent.change(input, { target: { value: "/pen" } });
    expect(within(screen.getByRole("listbox")).getAllByRole("option").map(option => option.textContent)).toEqual(["Penetration testing107"]);
    fireEvent.change(input, { target: { value: "/vuln" } });
    expect(within(screen.getByRole("listbox")).getAllByRole("option")).toHaveLength(2);
    fireEvent.change(input, { target: { value: "/zzz" } });
    expect(screen.getByText("No topic matches “zzz”.")).toBeInTheDocument();
  });

  it("moves with the arrow keys, selects with Enter or Tab, clears the slash text and does not send", async () => {
    const turn = answering();
    mount();
    const input = await slash("/vuln");
    fireEvent.keyDown(input, { key: "ArrowDown" });
    const options = within(screen.getByRole("listbox")).getAllByRole("option");
    expect(options[1]).toHaveAttribute("aria-selected", "true");
    expect(input).toHaveAttribute("aria-activedescendant", options[1].id);
    fireEvent.keyDown(input, { key: "ArrowDown" });
    expect(options[0]).toHaveAttribute("aria-selected", "true");
    fireEvent.keyDown(input, { key: "ArrowUp" });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    expect(input).toHaveValue("");
    expect(screen.getByRole("button", { name: "Remove topic Vulnerability repair" })).toBeInTheDocument();

    fireEvent.change(input, { target: { value: "/fu" } });
    fireEvent.keyDown(input, { key: "Tab" });
    expect(screen.getByRole("button", { name: "Remove topic Fuzzing" })).toBeInTheDocument();
    expect(input).toHaveValue("");
    expect(turn).not.toHaveBeenCalled();
  });

  it("closes on Escape and leaves the text; Enter then sends it and Shift+Enter is untouched", async () => {
    const turn = answering();
    mount();
    const input = await slash("/pen");
    fireEvent.keyDown(input, { key: "Enter", shiftKey: true });
    expect(turn).not.toHaveBeenCalled();
    fireEvent.keyDown(input, { key: "Escape" });
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    expect(input).toHaveValue("/pen");
    expect(input).not.toHaveAttribute("aria-activedescendant");
    expect(turn).not.toHaveBeenCalled();
    fireEvent.change(input, { target: { value: "/pen and paper threat models" } });
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    fireEvent.keyDown(input, { key: "Enter" });
    await waitFor(() => expect(turn).toHaveBeenCalledWith("/pen and paper threat models", null, "chat_page", "/", expect.any(AbortSignal)));
  });

  it("does not hijack a slash later in the question", async () => {
    mount();
    await slash("What about /etc/passwd?");
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });

  it("opens from the / button without the slash key and keeps the visitor's text", async () => {
    mount();
    const input = await slash("Half a question");
    const button = screen.getByRole("button", { name: "Topics" });
    expect(button).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(button);
    expect(button).toHaveAttribute("aria-expanded", "true");
    expect(input).toHaveFocus();
    fireEvent.click(within(screen.getByRole("listbox")).getByRole("option", { name: /AI-system security/ }));
    expect(input).toHaveValue("Half a question");
    expect(screen.getByRole("button", { name: "Remove topic AI-system security" })).toBeInTheDocument();
  });

  it("works in the Ask panel, where Escape closes the list but not the panel", async () => {
    mount(<><AssistantAskButton /><AssistantPanel /></>);
    fireEvent.click(screen.getByRole("button", { name: "Ask" }));
    const input = await box();
    await screen.findByText(/Or pick a topic/);
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: "/pen" } });
    expect(screen.getByRole("listbox")).toBeInTheDocument();
    fireEvent.keyDown(input, { key: "Escape" });
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("works in the landing box, which starts the chat with the chosen topic", async () => {
    const turn = answering();
    mount(<Routes><Route path="/" element={<AssistantLanding />} /><Route path="/chat/:sessionId?" element={<AssistantPage />} /></Routes>);
    const input = screen.getByLabelText("Ask the catalog");
    await waitFor(() => expect(input).toBeEnabled());
    await screen.findByRole("button", { name: "Topics" });
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: "/pen" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(turn).not.toHaveBeenCalled();
    expect(input).toHaveValue("");
    expect(input).toHaveAttribute("placeholder", "Ask about penetration testing…");
    fireEvent.change(input, { target: { value: "Who automates recon?" } });
    fireEvent.keyDown(input, { key: "Enter" });
    await screen.findByText("Answer");
    expect(turn).toHaveBeenCalledWith("Who automates recon?", null, "landing", "/", expect.any(AbortSignal), "penetration-testing");
    expect(screen.getByText("Topic: Penetration testing")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Remove topic Penetration testing" })).toBeInTheDocument();
  });
});

describe("topic analytics", () => {
  it("lets only topic_chosen carry a slug-shaped topic and keeps Do Not Track", () => {
    const send = (event: string, properties: Record<string, unknown>) =>
      catalogOptions.before_send({ uuid: "test", event, properties: { catalog_environment: "preview", surface: "panel", ...properties } })?.properties;
    expect(send("assistant_topic_chosen", { topic: "penetration-testing", question: "private" })).toEqual({ catalog_environment: "preview", surface: "panel", topic: "penetration-testing", $geoip_disable: true, $process_person_profile: false });
    expect(send("assistant_topic_chosen", { topic: "Which harness is best?" })).not.toHaveProperty("topic");
    expect(send("assistant_follow_up_clicked", { topic: "fuzzing", question: "private" })).toEqual({ catalog_environment: "preview", surface: "panel", $geoip_disable: true, $process_person_profile: false });
    expect(send("assistant_slash_menu_used", {})).toBeDefined();
    const capture = vi.spyOn(posthog, "capture").mockReturnValue(undefined);
    vi.stubEnv("VITE_LOCAL_CATALOG", "true"); vi.stubEnv("VITE_POSTHOG_PROJECT_TOKEN", "phc_test");
    assistantEvent("topic_chosen", "panel", "Not a slug");
    expect(capture).toHaveBeenLastCalledWith("assistant_topic_chosen", { surface: "panel", catalog_environment: "preview" });
    vi.stubGlobal("navigator", { doNotTrack: "1" });
    for (const action of ["topic_chosen", "slash_menu_used", "follow_up_clicked"] as const) assistantEvent(action, "panel", "fuzzing");
    expect(capture).toHaveBeenCalledTimes(1);
  });
});
