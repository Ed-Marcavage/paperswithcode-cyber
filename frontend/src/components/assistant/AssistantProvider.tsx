import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { assistantApi, assistantKeys, AssistantError, type AssistantConversation, type AssistantMessage, type AssistantSurface } from "@/lib/api/assistant";
import { AssistantContext } from "./context";
import "./assistant.css";

const OPEN_KEY = "pwc:assistant:open";
const ID_KEY = "pwc:assistant:conversation";
function stored(key: string) { try { return localStorage.getItem(key); } catch { return null; } }
function remember(key: string, value: string | null) {
  try { if (value === null) localStorage.removeItem(key); else localStorage.setItem(key, value); } catch { /* Private browsing still supports this visit. */ }
}
function empty(): AssistantConversation {
  return { id: "", title: "New chat", updated_at: "", question_count: 0, question_limit: 10, messages: [] };
}

export function AssistantProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [open, updateOpen] = useState(() => stored(OPEN_KEY) === "true");
  const [currentId, updateId] = useState<string | null>(() => stored(ID_KEY));
  const [conversation, setConversation] = useState(empty);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(Boolean(currentId));
  const [error, setError] = useState<AssistantError | null>(null);
  const active = useRef<AbortController | null>(null);
  const revision = useRef(0);
  const setOpen = useCallback((value: boolean) => { updateOpen(value); remember(OPEN_KEY, String(value)); }, []);
  const setId = useCallback((id: string | null) => { updateId(id); remember(ID_KEY, id); }, []);

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
  const newChat = useCallback(() => {
    active.current?.abort(); active.current = null; revision.current += 1;
    setBusy(false); setLoading(false); setError(null); setDraft(""); setConversation(empty()); setId(null);
  }, [setId]);

  const send = useCallback(async (question: string, surface: AssistantSurface, path: string) => {
    if (active.current || !question.trim() || question.length > 1000 || loading) return;
    const controller = new AbortController();
    active.current = controller;
    const version = revision.current;
    const answerId = crypto.randomUUID();
    const answer: AssistantMessage = { id: answerId, role: "assistant", content: "", status: "running", tool_steps: [] };
    const priorId = currentId;
    setBusy(true); setError(null); setDraft("");
    setConversation(previous => ({ ...previous, messages: [...previous.messages,
      { id: crypto.randomUUID(), role: "user", content: question, status: "done", tool_steps: [] }, answer] }));
    const updateAnswer = (update: (message: AssistantMessage) => AssistantMessage) => {
      if (version !== revision.current) return;
      setConversation(previous => ({ ...previous, messages: previous.messages.map(m => m.id === answerId ? update(m) : m) }));
    };
    try {
      // Establish the HttpOnly visitor cookie before a first POST; also dedupes
      // a simultaneous sidebar request through the same TanStack Query key.
      await queryClient.ensureQueryData({ queryKey: assistantKeys.list, queryFn: assistantApi.list });
      controller.signal.throwIfAborted();
      for await (const event of assistantApi.turn(question, priorId, surface, path, controller.signal)) {
        if (version !== revision.current) break;
        if (event.type === "meta") {
          setId(event.conversation_id);
          setConversation(previous => ({ ...previous, id: event.conversation_id,
            question_count: event.question_count, question_limit: event.question_limit }));
          updateAnswer(m => ({ ...m, run_id: event.run_id }));
        } else if (event.type === "text_delta") updateAnswer(m => ({ ...m, content: m.content + event.text }));
        else if (event.type === "tool_started") updateAnswer(m => ({ ...m, tool_steps: [...m.tool_steps,
          { name: event.name, call_id: event.id, pending: true }] }));
        else if (event.type === "tool_finished") updateAnswer(m => ({ ...m, tool_steps: m.tool_steps.map(s => s.call_id === event.id ? { ...s, pending: false, error: event.error, result: event.result } : s) }));
        else if (event.type === "done") updateAnswer(m => ({ ...m, status: event.status }));
        else if (event.type === "error") throw new AssistantError(event.message, event.code, 0, event.retry_at);
      }
    } catch (failure) {
      if (version !== revision.current) return;
      if (controller.signal.aborted) updateAnswer(m => ({ ...m, status: "cancelled" }));
      else {
        const problem = failure instanceof AssistantError ? failure : new AssistantError("The assistant could not respond. Please try again.");
        setError(problem); setDraft(question);
        updateAnswer(m => ({ ...m, status: "failed", error: problem.message }));
      }
    } finally {
      if (version === revision.current) { active.current = null; setBusy(false); }
      void queryClient.invalidateQueries({ queryKey: assistantKeys.list });
    }
  }, [currentId, loading, queryClient, setId]);

  return <AssistantContext.Provider value={{ open, setOpen, currentId, conversation, draft, setDraft, busy, loading, error,
    send, selectConversation, newChat, stop }}>{children}</AssistantContext.Provider>;
}
