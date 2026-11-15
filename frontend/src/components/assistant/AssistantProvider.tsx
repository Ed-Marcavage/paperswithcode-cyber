import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { assistantApi, assistantKeys, AssistantError, type AssistantConversation, type AssistantMessage, type AssistantSurface } from "@/lib/api/assistant";
import { AssistantContext } from "./context";
import "./assistant.css";
import { useAvailability } from "./useAvailability";
import { assistantEvent } from "@/lib/catalogAnalytics";

const OPEN_KEY = "pwc:assistant:open";
const ID_KEY = "pwc:assistant:conversation";
function stored(key: string) { try { return localStorage.getItem(key); } catch { return null; } }
function remember(key: string, value: string | null) {
  try { if (value === null) localStorage.removeItem(key); else localStorage.setItem(key, value); } catch { /* Private browsing still supports this visit. */ }
}
interface SendOptions { fresh?: boolean; keepDraft?: boolean; topic?: string | null }
function empty(): AssistantConversation {
  return { id: "", title: "New chat", updated_at: "", question_count: 0, question_limit: 10, messages: [] };
}

export function AssistantProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const availability = useAvailability();
  const [open, updateOpen] = useState(() => stored(OPEN_KEY) === "true");
  const [currentId, updateId] = useState<string | null>(() => stored(ID_KEY));
  const [conversation, setConversation] = useState(empty);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(Boolean(currentId));
  const [error, setError] = useState<AssistantError | null>(null);
  // The chosen topic per conversation ("" is the new, unsaved chat). Memory only, never
  // localStorage: it stays set for the conversation until removed or a new chat starts.
  const [topicByChat, setTopicByChat] = useState<Record<string, string>>({});
  const topicsQuery = useQuery({ queryKey: assistantKeys.topics, queryFn: assistantApi.topics, staleTime: 30 * 60_000, retry: false });
  const topics = topicsQuery.data ?? [];
  const topic = topicByChat[currentId ?? ""] ?? null;
  const active = useRef<AbortController | null>(null);
  const revision = useRef(0);
  const setOpen = useCallback((value: boolean) => { updateOpen(value); remember(OPEN_KEY, String(value)); if (value) assistantEvent("opened", "panel"); }, []);
  const setId = useCallback((id: string | null) => { updateId(id); remember(ID_KEY, id); }, []);
  const setTopic = useCallback((slug: string | null, surface: AssistantSurface = "panel") => {
    const key = currentId ?? "";
    setTopicByChat(previous => {
      const next = { ...previous };
      if (slug) next[key] = slug; else delete next[key];
      return next;
    });
    if (slug) assistantEvent("topic_chosen", surface, slug);
  }, [currentId]);

  useEffect(() => {
    if (!currentId || active.current) return;
    let disposed = false;
    setLoading(true);
    void queryClient.fetchQuery({ queryKey: assistantKeys.conversation(currentId), queryFn: () => assistantApi.conversation(currentId), staleTime: 0 })
      .then(value => { if (!disposed) setConversation(value); })
      .catch((failure: unknown) => {
        if (disposed) return;
        setError(failure instanceof AssistantError ? failure : new AssistantError("Your chat could not be loaded. Please try again."));
        if (failure instanceof AssistantError && failure.status === 404) { setId(null); setConversation(empty()); }
      }).finally(() => { if (!disposed) setLoading(false); });
    return () => { disposed = true; };
  }, [currentId, queryClient, setId]);
  useEffect(() => () => active.current?.abort(), []);

  const stop = useCallback(() => active.current?.abort(), []);
  const selectConversation = useCallback((id: string) => {
    if (id === currentId) return;
    active.current?.abort(); active.current = null; revision.current += 1;
    setBusy(false); setError(null); setDraft(""); setConversation(empty()); setLoading(true); setId(id);
  }, [currentId, setId]);
  const newChat = useCallback((surface: AssistantSurface = "panel") => {
    assistantEvent("new_chat", surface);
    active.current?.abort(); active.current = null; revision.current += 1;
    setBusy(false); setLoading(false); setError(null); setDraft(""); setConversation(empty()); setId(null);
    setTopicByChat(({ "": _unsaved, ...saved }) => saved);
  }, [setId]);

  const send = useCallback(async (question: string, surface: AssistantSurface, path: string, { fresh = false, keepDraft = false, topic: chosen }: SendOptions = {}) => {
    if (active.current || !availability.available || !question.trim() || question.length > 1000 || (loading && !fresh)) return;
    const controller = new AbortController();
    active.current = controller;
    const version = revision.current;
    const answerId = crypto.randomUUID();
    const answer: AssistantMessage = { id: answerId, role: "assistant", content: "", status: "running", tool_steps: [] };
    const priorId = fresh ? null : currentId;
    const sentTopic = chosen === undefined ? topic : chosen;
    assistantEvent("message_sent", surface);
    setBusy(true); setError(null); if (!keepDraft) setDraft("");
    setConversation(previous => ({ ...previous, messages: [...previous.messages,
      { id: crypto.randomUUID(), role: "user", content: question, status: "done", tool_steps: [], topic: sentTopic }, answer] }));
    const updateAnswer = (update: (message: AssistantMessage) => AssistantMessage) => {
      if (version !== revision.current) return;
      setConversation(previous => ({ ...previous, messages: previous.messages.map(m => m.id === answerId ? update(m) : m) }));
    };
    try {
      // Establish the HttpOnly visitor cookie before a first POST; also dedupes
      // a simultaneous sidebar request through the same TanStack Query key.
      await queryClient.ensureQueryData({ queryKey: assistantKeys.list, queryFn: assistantApi.list });
      controller.signal.throwIfAborted();
      for await (const event of assistantApi.turn(question, priorId, surface, path, controller.signal, ...(sentTopic ? [sentTopic] as const : [] as const))) {
        if (version !== revision.current) break;
        if (event.type === "meta") {
          // A new chat's topic now belongs to its saved id.
          if (!priorId) setTopicByChat(({ "": unsaved, ...saved }) => unsaved ? { ...saved, [event.conversation_id]: unsaved } : saved);
          setId(event.conversation_id);
          setConversation(previous => ({ ...previous, id: event.conversation_id,
            question_count: event.question_count, question_limit: event.question_limit }));
          updateAnswer(m => ({ ...m, run_id: event.run_id }));
        } else if (event.type === "working_note") updateAnswer(m => ({ ...m, working_note: event.text }));
        else if (event.type === "text_delta") updateAnswer(m => ({ ...m, content: m.content + event.text, working_note: undefined }));
        else if (event.type === "tool_started") updateAnswer(m => ({ ...m, tool_steps: [...m.tool_steps,
          { name: event.name, call_id: event.id, pending: true }] }));
        else if (event.type === "tool_finished") updateAnswer(m => ({ ...m, tool_steps: m.tool_steps.map(s => s.call_id === event.id ? { ...s, pending: false, error: event.error, result: event.result } : s) }));
        else if (event.type === "done") { updateAnswer(m => ({ ...m, status: event.status })); assistantEvent("answer_done", surface); if (event.status === "limit_reached") assistantEvent("limit_hit", surface); }
        else if (event.type === "error") throw new AssistantError(event.message, event.code, 0, event.retry_at);
      }
    } catch (failure) {
      if (version !== revision.current) return;
      if (controller.signal.aborted) updateAnswer(m => ({ ...m, status: "cancelled" }));
      else {
        const problem = failure instanceof AssistantError ? failure : new AssistantError("The assistant could not respond. Please try again.");
        assistantEvent(["usage_limit", "question_limit"].includes(problem.code) ? "limit_hit" : "error", surface);
        setError(problem); if (!keepDraft) setDraft(question);
        if (["usage_limit", "disabled", "not_configured"].includes(problem.code)) {
          queryClient.setQueryData(assistantKeys.status, { available: false, code: problem.code, reason: problem.message, retry_at: problem.retryAt });
        }
        if (problem.code === "question_limit") setConversation(previous => ({ ...previous, question_count: previous.question_limit }));
        updateAnswer(m => ({ ...m, status: "failed", error: problem.message }));
      }
    } finally {
      updateAnswer(m => ({ ...m, working_note: undefined }));
      if (version === revision.current) { active.current = null; setBusy(false); }
      void queryClient.invalidateQueries({ queryKey: assistantKeys.list });
    }
  }, [currentId, loading, queryClient, setId, availability.available, topic]);

  const launch = (question: string, path: string, chosen: string | null = null) => {
    newChat("landing"); assistantEvent("asked_from_landing", "landing");
    if (chosen) setTopicByChat(previous => ({ ...previous, "": chosen }));
    void send(question, "landing", path, { fresh: true, topic: chosen });
  };

  return <AssistantContext.Provider value={{ open, setOpen, currentId, conversation, draft, setDraft, busy, loading, error,
    availability, launch, send, selectConversation, newChat, stop, topics, topic, setTopic }}>{children}</AssistantContext.Provider>;
}
