import { useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useAssistant } from "./context";
import { useRotatingPlaceholder } from "./useRotatingPlaceholder";
import { ASSISTANT_PROMPTS } from "./prompts";
import { AssistantIcon } from "./icons";
import { useAutosize } from "./format";

const DISABLED_FLOOR: readonly string[] = [];

export function AssistantLanding() {
  const chat = useAssistant();
  const [question, setQuestion] = useState("");
  const field = useRef<HTMLTextAreaElement>(null);
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const { placeholder, prompt } = useRotatingPlaceholder(!question && chat.availability.available);
  const disabled = !chat.availability.available;
  const reason = chat.availability.reason ?? "The assistant is unavailable.";
  // While empty, reserve the height of the longest example so the rotating
  // placeholder wraps instead of clipping, and the page below never jumps.
  useAutosize(field, question, 168, disabled ? DISABLED_FLOOR : ASSISTANT_PROMPTS, disabled ? undefined : prompt);
  const submit = () => {
    if (disabled || !question.trim() || question.length > 1000) return;
    chat.launch(question.trim(), pathname); chat.setOpen(false); navigate("/chat");
  };
  return <form className={`assistant-landing ph-mask${disabled ? " is-paused" : ""}`} onSubmit={event => { event.preventDefault(); submit(); }}>
    <label className="sr-only" htmlFor="assistant-landing-question">Ask the catalog</label>
    <div className="assistant-landing-field" onClick={event => { if (event.target === event.currentTarget) field.current?.focus(); }}>
      <textarea ref={field} id="assistant-landing-question" rows={1} maxLength={1000} value={question} disabled={disabled}
        placeholder={disabled ? reason : placeholder} aria-describedby={disabled ? undefined : "assistant-landing-hint"}
        title={disabled ? reason : "Press Tab to use the example question"}
        onChange={event => setQuestion(event.target.value)} onKeyDown={event => {
          if (event.nativeEvent.isComposing) return;
          if (event.key === "Tab" && !event.shiftKey && !question && !disabled) { event.preventDefault(); setQuestion(prompt); }
          if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); submit(); }
        }} />
      <button type="submit" className="assistant-send" disabled={disabled || !question.trim()} title="Ask">
        <AssistantIcon name="send" /><span className="sr-only">Ask</span></button>
    </div>
    {!disabled && <p id="assistant-landing-hint" className="assistant-landing-hint"><kbd>Tab</kbd> uses the example, <kbd>Enter</kbd> asks</p>}
  </form>;
}
