import { useLayoutEffect, useMemo, useRef } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { followUps, type AssistantSurface } from "@/lib/api/assistant";
import { assistantEvent } from "@/lib/catalogAnalytics";
import { useAssistant } from "./context";
import { AssistantMarkdown } from "./AssistantMarkdown";
import { AssistantToolSteps } from "./AssistantToolSteps";
import { evidenceLinks } from "./markdown";
import { ASSISTANT_PROMPTS } from "./prompts";
import { AssistantFeedback } from "./AssistantFeedback";
import { AssistantIcon } from "./icons";
import { useAutosize } from "./format";
import { TopicButton, TopicChips, TopicTag } from "./AssistantTopics";
import { inSentence, topicLabel } from "./topics";
import { useCommandMenu } from "./useCommandMenu";

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
  const topic = paused ? null : chat.topic;
  const label = topicLabel(chat.topics, topic);
  const chooseTopic = (slug: string | null) => { chat.setTopic(slug, surface); field.current?.focus(); };
  const menu = useCommandMenu({ topics: chat.topics, draft: chat.draft, setDraft: chat.setDraft, onTopic: chooseTopic, field, surface, enabled: !disabled });
  const last = messages[messages.length - 1];
  // Only the latest finished answer offers next questions, and only while one can be asked.
  const suggestions = !disabled && last?.role === "assistant" && last.status === "done" ? followUps(last.follow_ups) : [];
  const ask = (question: string) => { assistantEvent("follow_up_clicked", surface); void chat.send(question, surface, pathname, { keepDraft: true }); };
  const offerTopics = chat.topics.length > 0 && !paused;
  const placeholder = !chat.availability.available ? chat.availability.reason ?? "The assistant is unavailable."
    : atLimit ? "Start a new chat to ask more"
    : label ? `${messages.length ? "Ask a follow-up about" : "Ask about"} ${inSentence(label)}…`
    : messages.length ? offerTopics ? "Ask a follow-up, or type / for a topic" : "Ask a follow-up…"
    : offerTopics ? "Ask about the catalog, or type / for topics" : "Ask about the catalog…";
  // Size the empty box to its placeholder, which changes with the topic and can wrap on phones.
  const floor = useMemo(() => [placeholder], [placeholder]);
  useAutosize(field, chat.draft, 200, floor, placeholder);

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
              onClick={() => { chat.setDraft(prompt); if (chat.topic) chat.setTopic(null, surface); field.current?.focus(); }}>{prompt}</button>)}</div>
            {offerTopics && <TopicChips topics={chat.topics} selected={chat.topic} onSelect={chooseTopic} disabled={disabled} />}
          </div> :
          messages.map(message => {
            const running = message.status === "running";
            const asked = message.role === "user" ? topicLabel(chat.topics, message.topic) : null;
            return <article key={message.id} className={`assistant-message assistant-message-${message.role}`}>
              <h3 className="sr-only">{message.role === "user" ? "You" : "Assistant"}</h3>
              {message.role === "user" ? <>
                {asked && <p className="assistant-question-topic">Topic: {asked}</p>}
                <div className="assistant-question">{message.content}</div>
              </> : <>
                <AssistantToolSteps steps={message.tool_steps} running={running} writing={Boolean(message.content)}
                  workingNote={running ? message.working_note : undefined} />
                {message.content && <AssistantMarkdown text={message.content} streaming={running} evidence={evidence} surface={surface} />}
                {message.status === "cancelled" && <p className="assistant-message-note">Stopped. Your partial answer is saved.</p>}
                <AssistantFeedback message={message} surface={surface} />
                {message === last && suggestions.length > 0 && <div className="assistant-follow-ups" role="group" aria-labelledby={`assistant-next-${surface}`}>
                  <p id={`assistant-next-${surface}`} className="assistant-follow-ups-label">Ask next</p>
                  <ul>{suggestions.map(question => <li key={question}><button type="button" onClick={() => ask(question)}>
                    <AssistantIcon name="next" size={14} /><span>{question}</span></button></li>)}</ul>
                </div>}
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
          <div className={`assistant-field${paused ? " is-paused" : ""}${offerTopics ? " has-topics" : ""}`} onClick={event => { if (event.target === event.currentTarget) field.current?.focus(); }}>
            {label && <TopicTag label={label} onRemove={() => { chat.setTopic(null, surface); field.current?.focus(); }} />}
            {offerTopics && <TopicButton {...menu.button} disabled={disabled} />}
            <label className="sr-only" htmlFor={`assistant-question-${surface}`}>Your question</label>
            <textarea ref={field} id={`assistant-question-${surface}`} value={chat.draft} disabled={disabled} maxLength={1000} rows={1}
              placeholder={placeholder} {...menu.inputProps}
              title={chat.availability.reason ?? undefined} onChange={event => chat.setDraft(event.target.value)}
              onKeyDown={event => {
                if (menu.onKeyDown(event)) return;
                if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); send(); }
              }} />
            {chat.busy ? <button type="button" className="assistant-send is-stop" aria-label="Stop" title="Stop the answer" onClick={chat.stop}><AssistantIcon name="stop" /></button>
              : <button type="submit" className="assistant-send" aria-label="Send" title="Send" disabled={disabled || !chat.draft.trim()}><AssistantIcon name="send" /></button>}
            {menu.menu}
          </div>
          {menu.status}
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
