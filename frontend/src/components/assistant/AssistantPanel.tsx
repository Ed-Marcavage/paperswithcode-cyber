import { useEffect, useLayoutEffect, useRef } from "react";
import { Link } from "react-router-dom";
import { useAssistant } from "./context";
import { AssistantConversationView } from "./AssistantConversation";
import { AssistantIcon } from "./icons";
import { PANEL_OPEN_CLASS, useOnChatPage } from "./format";


export function AssistantAskButton() {
  const { open, setOpen } = useAssistant();
  if (useOnChatPage()) return null;
  return <button type="button" id="assistant-ask-button" className={`assistant-ask-trigger${open ? " is-open" : ""}`} title={open ? "Close the assistant" : "Ask the catalog"}
    aria-expanded={open} aria-controls="assistant-panel" onClick={() => setOpen(!open, "ask_button")}><AssistantIcon name="ask" size={14} /><span>Ask</span></button>;
}

export function AssistantPanel() {
  const { open, setOpen, currentId, newChat, conversation } = useAssistant();
  const onChatPage = useOnChatPage();
  const visible = open && !onChatPage;
  const panel = useRef<HTMLElement>(null);
  useLayoutEffect(() => {
    const root = document.documentElement;
    root.classList.toggle(PANEL_OPEN_CLASS, visible);
    if (!visible) return;
    // Sit below the sticky site header on wide screens; follow its real height.
    const header = document.querySelector<HTMLElement>(".app-header");
    const measure = () => root.style.setProperty("--assistant-header-height", `${header?.offsetHeight ?? 0}px`);
    measure();
    const observer = header && typeof ResizeObserver !== "undefined" ? new ResizeObserver(measure) : null;
    if (header) observer?.observe(header);
    return () => { observer?.disconnect(); root.classList.remove(PANEL_OPEN_CLASS); };
  }, [visible]);
  useEffect(() => {
    if (!visible) return;
    // The question box when it can take input, otherwise the panel itself, so a
    // loading chat does not leave a focus ring on the first header button.
    (panel.current?.querySelector<HTMLElement>("textarea:enabled") ?? panel.current)?.focus();
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !event.defaultPrevented) { event.preventDefault(); setOpen(false); }
    };
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("keydown", escape);
      document.getElementById("assistant-ask-button")?.focus();
    };
  }, [visible, setOpen]);
  if (!visible) return null;
  const title = conversation.messages.length ? conversation.title : "";
  return <>
    <div className="assistant-panel-backdrop" aria-hidden="true" onClick={() => setOpen(false)} />
    <aside id="assistant-panel" ref={panel} className="assistant-panel" role="dialog" tabIndex={-1} aria-label="Ask the catalog">
      <div className="assistant-panel-header">
        <div className="assistant-panel-heading">
          <h2>Ask the catalog</h2>
          {/* The chat title is the visitor's first question: masked text, and no title attribute (replay records attributes). */}
          {title && title !== "New chat" && <p className="assistant-panel-subtitle ph-mask">{title}</p>}
        </div>
        <button type="button" className="assistant-icon-button" aria-label="New chat" title="New chat" onClick={() => newChat()}><AssistantIcon name="plus" /></button>
        <Link className="assistant-icon-button" to={currentId ? `/chat/${currentId}` : "/chat"} aria-label="All chats" title="Open in the chat page with all your chats"
          onClick={() => setOpen(false)}><AssistantIcon name="expand" /></Link>
        <button type="button" className="assistant-icon-button" aria-label="Close assistant" title="Close (Esc)" onClick={() => setOpen(false)}><AssistantIcon name="close" /></button>
      </div>
      <AssistantConversationView />
    </aside>
  </>;
}
