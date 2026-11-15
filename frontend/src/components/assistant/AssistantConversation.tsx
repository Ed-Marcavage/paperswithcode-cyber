import { useLocation, useNavigate } from "react-router-dom";
import type { AssistantSurface } from "@/lib/api/assistant";
import { useAssistant } from "./context";
import { AssistantMarkdown } from "./AssistantMarkdown";
import { AssistantToolSteps } from "./AssistantToolSteps";
import { evidenceLinks } from "./markdown";
import { ASSISTANT_PROMPTS } from "./prompts";
import { AssistantFeedback } from "./AssistantFeedback";

export function AssistantConversationView({ surface = "panel" }: { surface?: AssistantSurface }) {
  const chat = useAssistant();
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const count = chat.conversation.question_count;
  const evidence = evidenceLinks(chat.conversation.messages);
  const atLimit = count >= chat.conversation.question_limit;
  const disabled = chat.busy || chat.loading || atLimit || !chat.availability.available;
  const send = () => { if (!disabled) void chat.send(chat.draft, surface, pathname); };
  return <div className="assistant-conversation">
    <div className="assistant-transcript ph-mask" aria-label="Conversation" aria-live="polite" aria-busy={chat.busy}>
      {chat.loading ? <p>Loading your chat…</p> : chat.conversation.messages.length === 0 ?
        <div className="assistant-empty"><p>Ask about papers, security research, repositories, organizations, or developers in the catalog.</p>
          <div className="assistant-examples">{ASSISTANT_PROMPTS.map(prompt => <button key={prompt} type="button" onClick={() => chat.setDraft(prompt)}>{prompt}</button>)}</div>
        </div> :
        chat.conversation.messages.map(message => <article key={message.id} className={`assistant-message assistant-message-${message.role}`}>
          <strong>{message.role === "user" ? "You" : "Assistant"}</strong>
          {message.role === "user" ? <div className="assistant-text">{message.content}</div> :
            <AssistantMarkdown text={message.content} streaming={message.status === "running"} evidence={evidence} surface={surface} />}
          <AssistantToolSteps steps={message.tool_steps} workingNote={message.status === "running" ? message.working_note : undefined} />
          {message.status === "cancelled" && <small>Stopped. Your partial answer is saved.</small>}
          {message.role === "assistant" && <AssistantFeedback message={message} surface={surface} />}
          {message.tool_steps.some(step => step.pending) && <span role="status">Searching the catalog…</span>}
        </article>)}
    </div>
    {!chat.availability.available && <p role="status" className="assistant-error">{chat.availability.reason}</p>}
    {atLimit && !chat.busy && <div className="assistant-error" role="status">This chat has reached 10 questions. <button type="button" onClick={() => { chat.newChat(surface); if (surface === "chat_page") navigate("/chat"); }}>New chat</button></div>}
    {chat.error && !["usage_limit", "question_limit", "disabled", "not_configured"].includes(chat.error.code) &&
      <p role="alert" className="assistant-error">{chat.error.message} <button type="button" disabled={disabled || !chat.draft.trim()} onClick={send}>Try again</button></p>}
    <form className="assistant-composer ph-mask" onSubmit={event => { event.preventDefault(); send(); }}>
      <label className="sr-only" htmlFor={`assistant-question-${surface}`}>Your question</label>
      <textarea id={`assistant-question-${surface}`} value={chat.draft} disabled={disabled} maxLength={1000} rows={3}
        placeholder={chat.availability.available ? "Ask about the catalog…" : chat.availability.reason ?? "The assistant is unavailable."}
        title={chat.availability.reason ?? undefined} onChange={event => chat.setDraft(event.target.value)}
        onKeyDown={event => {
          if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); send(); }
        }} />
      <div className="assistant-composer-footer">
        <span>Question {Math.min(count + (chat.busy ? 0 : 1), 10) || 1} of 10</span>
        {chat.draft.length >= 800 && <span aria-live="polite">{chat.draft.length}/1000</span>}
        {chat.busy ? <button type="button" onClick={chat.stop}>Stop</button> : <button type="submit" disabled={disabled || !chat.draft.trim()}>Send</button>}
      </div>
    </form>
  </div>;
}
