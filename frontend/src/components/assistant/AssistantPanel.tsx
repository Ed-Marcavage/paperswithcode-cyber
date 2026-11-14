import { useEffect, useRef } from "react";
import { Link } from "react-router-dom";
import { useAssistant } from "./context";
import { AssistantConversationView } from "./AssistantConversation";

export function AssistantAskButton() {
  const { open, setOpen } = useAssistant();
  return <button type="button" id="assistant-ask-button" className="assistant-ask-trigger"
    aria-expanded={open} aria-controls="assistant-panel" onClick={() => setOpen(!open)}>Ask</button>;
}

export function AssistantPanel() {
  const { open, setOpen, currentId, newChat } = useAssistant();
  const panel = useRef<HTMLElement>(null);
  useEffect(() => {
    if (!open) return;
    (panel.current?.querySelector<HTMLElement>("textarea:enabled") ?? panel.current?.querySelector<HTMLElement>("button"))?.focus();
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") { event.preventDefault(); setOpen(false); }
    };
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("keydown", escape);
      document.getElementById("assistant-ask-button")?.focus();
    };
  }, [open, setOpen]);
  if (!open) return null;
  return <aside id="assistant-panel" ref={panel} className="assistant-panel" role="dialog" aria-label="Ask the catalog">
    <div className="assistant-panel-header"><h2>Ask the catalog</h2>
      <button type="button" aria-label="Close assistant" onClick={() => setOpen(false)}>×</button>
    </div>
    <nav className="assistant-panel-actions" aria-label="Chat navigation"><button type="button" onClick={() => newChat()}>New chat</button>
      <Link to={currentId ? `/chat/${currentId}` : "/chat"} onClick={() => setOpen(false)}>All chats</Link></nav>
    <AssistantConversationView />
  </aside>;
}
