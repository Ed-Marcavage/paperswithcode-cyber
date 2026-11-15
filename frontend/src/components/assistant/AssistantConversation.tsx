import { useLayoutEffect, useRef } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import type { AssistantSurface } from "@/lib/api/assistant";
import { useAssistant } from "./context";
import { AssistantMarkdown } from "./AssistantMarkdown";
import { AssistantToolSteps } from "./AssistantToolSteps";
import { evidenceLinks } from "./markdown";
import { ASSISTANT_PROMPTS } from "./prompts";
import { AssistantFeedback } from "./AssistantFeedback";
import { AssistantIcon } from "./icons";
import { useAutosize } from "./format";

export function AssistantConversationView({ surface = "panel" }: { surface?: AssistantSurface }) {
  const chat = useAssistant();
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const transcript = useRef<HTMLDivElement>(null);
  const field = useRef<HTMLTextAreaElement>(null);
  const pinned = useRef(true);
  const shown = useRef({ id: "", count: 0 });
  const { messages, question_count: count, question_limit: limit } = chat.conversation;
  const evidence = evidenceLinks(messages);
  const atLimit = count >= limit;
  const disabled = chat.busy || chat.loading || atLimit || !chat.availability.available;
  const paused = !chat.availability.available || atLimit;
  const send = () => { if (!disabled) void chat.send(chat.draft, surface, pathname); };
  useAutosize(field, chat.draft, 200);

  // Follow the answer while the reader is at the bottom; a new question or a
  // newly opened chat always jumps to the latest turn.
  useLayoutEffect(() => {
    const el = transcript.current;
    if (!el) return;
    const fresh = shown.current.id !== chat.conversation.id || messages.length > shown.current.count;
    shown.current = { id: chat.conversation.id, count: messages.length };
    if (fresh || pinned.current) { el.scrollTop = el.scrollHeight; pinned.current = true; }
  }, [chat.conversation.id, messages]);

  return <div className={`assistant-conversation assistant-surface-${surface}`}>
    <div ref={transcript} className="assistant-transcript ph-mask" aria-label="Conversation" aria-live="polite" aria-busy={chat.busy}
      onScroll={event => { const el = event.currentTarget; pinned.current = el.scrollHeight - el.scrollTop - el.clientHeight < 48; }}>
      <div className="assistant-column">
        {chat.loading ? <p className="assistant-loading">Loading your chat…</p> : messages.length === 0 ?
          <div className="assistant-empty">
            <h2 className="assistant-empty-title">Ask the <em>catalog</em></h2>
            <p>Ask about papers, industry posts, repositories, organizations or developers in the catalog. Answers link to the entries they draw on.</p>
            <div className="assistant-examples" aria-label="Example questions" role="group">{ASSISTANT_PROMPTS.map(prompt => <button key={prompt} type="button"
              onClick={() => { chat.setDraft(prompt); field.current?.focus(); }}>{prompt}</button>)}</div>
          </div> :
          messages.map(message => {
            const running = message.status === "running";
            return <article key={message.id} className={`assistant-message assistant-message-${message.role}`}>
              <h3 className="sr-only">{message.role === "user" ? "You" : "Assistant"}</h3>
              {message.role === "user" ? <div className="assistant-question">{message.content}</div> : <>
                <AssistantToolSteps steps={message.tool_steps} running={running} writing={Boolean(message.content)}
                  workingNote={running ? message.working_note : undefined} />
                {message.content && <AssistantMarkdown text={message.content} streaming={running} evidence={evidence} surface={surface} />}
                {message.status === "cancelled" && <p className="assistant-message-note">Stopped. Your partial answer is saved.</p>}
                <AssistantFeedback message={message} surface={surface} />
              </>}
            </article>;
          })}
      </div>
    </div>
    <div className="assistant-dock">
      <div className="assistant-column">
        {!chat.availability.available && <p role="status" className="assistant-notice is-paused">{chat.availability.reason}</p>}
        {atLimit && !chat.busy && <div className="assistant-notice is-paused" role="status">
          <span>This chat has reached its {limit}-question limit. Start a new chat to keep asking.</span>
          <button type="button" onClick={() => { chat.newChat(surface); if (surface === "chat_page") navigate("/chat"); }}>New chat</button></div>}
        {chat.error && !["usage_limit", "question_limit", "disabled", "not_configured"].includes(chat.error.code) &&
          <div role="alert" className="assistant-notice is-error"><span>{chat.error.message}</span>
            <button type="button" disabled={disabled || !chat.draft.trim()} onClick={send}>Try again</button></div>}
        <form className="assistant-composer ph-mask" onSubmit={event => { event.preventDefault(); send(); }}>
          <div className={`assistant-field${paused ? " is-paused" : ""}`} onClick={event => { if (event.target === event.currentTarget) field.current?.focus(); }}>
            <label className="sr-only" htmlFor={`assistant-question-${surface}`}>Your question</label>
            <textarea ref={field} id={`assistant-question-${surface}`} value={chat.draft} disabled={disabled} maxLength={1000} rows={1}
              placeholder={chat.availability.available ? atLimit ? "Start a new chat to ask more" : messages.length ? "Ask a follow-up…" : "Ask about the catalog…" : chat.availability.reason ?? "The assistant is unavailable."}
              title={chat.availability.reason ?? undefined} onChange={event => chat.setDraft(event.target.value)}
              onKeyDown={event => {
                if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); send(); }
              }} />
            {chat.busy ? <button type="button" className="assistant-send is-stop" aria-label="Stop" title="Stop the answer" onClick={chat.stop}><AssistantIcon name="stop" /></button>
              : <button type="submit" className="assistant-send" aria-label="Send" title="Send" disabled={disabled || !chat.draft.trim()}><AssistantIcon name="send" /></button>}
          </div>
          <div className="assistant-composer-meta">
            {!atLimit && <span>Question {Math.min(count + (chat.busy ? 0 : 1), limit) || 1} of {limit}</span>}
            {chat.draft.length >= 800 && <span className={`assistant-count${chat.draft.length >= 1000 ? " is-full" : ""}`} aria-live="polite">{chat.draft.length}/1000</span>}
            <span className="assistant-composer-hint"><kbd>Enter</kbd> to send, <kbd>Shift</kbd>+<kbd>Enter</kbd> for a new line</span>
          </div>
        </form>
      </div>
    </div>
  </div>;
}
