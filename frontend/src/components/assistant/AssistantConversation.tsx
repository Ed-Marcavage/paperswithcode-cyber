import { useLocation } from "react-router-dom";
import type { AssistantSurface } from "@/lib/api/assistant";
import { useAssistant } from "./context";

export function AssistantConversationView({ surface = "panel" }: { surface?: AssistantSurface }) {
  const chat = useAssistant();
  const { pathname } = useLocation();
  const count = chat.conversation.question_count;
  const disabled = chat.busy || chat.loading || count >= chat.conversation.question_limit;
  const send = () => { if (!disabled) void chat.send(chat.draft, surface, pathname); };
  return <div className="assistant-conversation">
    <div className="assistant-transcript ph-mask" aria-label="Conversation" aria-live="polite" aria-busy={chat.busy}>
      {chat.loading ? <p>Loading your chat…</p> : chat.conversation.messages.length === 0 ?
        <p className="assistant-empty">Ask about papers, security research, repositories, organizations, or developers in the catalog.</p> :
        chat.conversation.messages.map(message => <article key={message.id} className={`assistant-message assistant-message-${message.role}`}>
          <strong>{message.role === "user" ? "You" : "Assistant"}</strong>
          <div className="assistant-text">{message.content}</div>
          {message.tool_steps.some(step => step.pending) && <span role="status">Searching the catalog…</span>}
        </article>)}
    </div>
    {chat.error && <p role="alert" className="assistant-error">{chat.error.message}</p>}
    <form className="assistant-composer ph-mask" onSubmit={event => { event.preventDefault(); send(); }}>
      <label className="sr-only" htmlFor={`assistant-question-${surface}`}>Your question</label>
      <textarea id={`assistant-question-${surface}`} value={chat.draft} disabled={disabled} maxLength={1000} rows={3}
        placeholder="Ask about the catalog…" onChange={event => chat.setDraft(event.target.value)}
        onKeyDown={event => {
          if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); send(); }
        }} />
      <div className="assistant-composer-footer">
        <span>Question {Math.min(count + (chat.busy ? 0 : 1), 10) || 1} of 10</span>
        {chat.draft.length >= 800 && <span aria-live="polite">{chat.draft.length}/1000</span>}
        <button type="submit" disabled={disabled || !chat.draft.trim()}>Send</button>
      </div>
    </form>
  </div>;
}
