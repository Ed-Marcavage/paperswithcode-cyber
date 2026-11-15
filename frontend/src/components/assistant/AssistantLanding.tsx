import { useRef, useState } from "react";
import { assistantEvent } from "@/lib/catalogAnalytics";
import { useLocation, useNavigate } from "react-router-dom";
import { useAssistant } from "./context";
import { useRotatingPlaceholder } from "./useRotatingPlaceholder";
import { ASSISTANT_PROMPTS } from "./prompts";
import { AssistantIcon } from "./icons";
import { useAutosize } from "./format";
import { TopicButton, TopicTag } from "./AssistantTopics";
import { inSentence, topicLabel } from "./topics";
import { useCommandMenu } from "./useCommandMenu";

const DISABLED_FLOOR: readonly string[] = [];

export function AssistantLanding() {
  const chat = useAssistant();
  const [question, setQuestion] = useState("");
  // The landing box always starts a new chat, so its topic is its own until it is sent.
  const [topic, setTopic] = useState<string | null>(null);
  const field = useRef<HTMLTextAreaElement>(null);
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const disabled = !chat.availability.available;
  const label = disabled ? null : topicLabel(chat.topics, topic);
  const { placeholder, prompt } = useRotatingPlaceholder(!question && !label && chat.availability.available);
  const menu = useCommandMenu({ topics: chat.topics, draft: question, setDraft: setQuestion, field, surface: "landing", enabled: !disabled,
    onTopic: slug => { setTopic(slug); assistantEvent("topic_chosen", "landing", slug); } });
  const offerTopics = chat.topics.length > 0 && !disabled;
  const reason = chat.availability.reason ?? "The assistant is unavailable.";
  // While empty, reserve the height of the longest example so the rotating
  // placeholder wraps instead of clipping, and the page below never jumps.
  useAutosize(field, question, 168, disabled ? DISABLED_FLOOR : ASSISTANT_PROMPTS, disabled ? undefined : prompt);
  const submit = () => {
    if (disabled || !question.trim() || question.length > 1000) return;
    chat.launch(question.trim(), pathname, label ? topic : null); chat.setOpen(false); navigate("/chat");
  };
  return <form className={`assistant-landing ph-mask${disabled ? " is-paused" : ""}`} onSubmit={event => { event.preventDefault(); submit(); }}>
    <label className="sr-only" htmlFor="assistant-landing-question">Ask the catalog</label>
    <div className={`assistant-landing-field${label ? " has-topic" : ""}`} onClick={event => { if (event.target === event.currentTarget) field.current?.focus(); }}>
      {label && <TopicTag label={label} onRemove={() => { setTopic(null); field.current?.focus(); }} />}
      <textarea ref={field} id="assistant-landing-question" rows={1} maxLength={1000} value={question} disabled={disabled}
        placeholder={disabled ? reason : label ? `Ask about ${inSentence(label)}…` : placeholder} aria-describedby={disabled ? undefined : "assistant-landing-hint"}
        title={disabled ? reason : label ? undefined : "Press Tab to use the example question"} {...menu.inputProps}
        onChange={event => setQuestion(event.target.value)} onKeyDown={event => {
          if (event.nativeEvent.isComposing || menu.onKeyDown(event)) return;
          if (event.key === "Tab" && !event.shiftKey && !question && !label && !disabled) { event.preventDefault(); setQuestion(prompt); }
          if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); submit(); }
        }} />
      {offerTopics && <TopicButton {...menu.button} />}
      <button type="submit" className="assistant-send" disabled={disabled || !question.trim()} title="Ask">
        <AssistantIcon name="send" /><span className="sr-only">Ask</span></button>
      {menu.menu}
    </div>
    {menu.status}
    {!disabled && <p id="assistant-landing-hint" className="assistant-landing-hint">{label ? <><kbd>Enter</kbd> asks about this topic</>
      : <><kbd>Tab</kbd> uses the example, {offerTopics && <><kbd>/</kbd> picks a topic, </>}<kbd>Enter</kbd> asks</>}</p>}
  </form>;
}
