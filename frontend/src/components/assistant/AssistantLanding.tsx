import { useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useAssistant } from "./context";
import { useRotatingPlaceholder } from "./useRotatingPlaceholder";

export function AssistantLanding() {
  const chat = useAssistant();
  const [question, setQuestion] = useState("");
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const { placeholder, prompt } = useRotatingPlaceholder(!question && chat.availability.available);
  const disabled = !chat.availability.available;
  const submit = () => {
    if (disabled || !question.trim() || question.length > 1000) return;
    chat.launch(question.trim(), pathname); chat.setOpen(false); navigate("/chat");
  };
  return <form className="assistant-landing ph-mask" onSubmit={event => { event.preventDefault(); submit(); }}>
    <label htmlFor="assistant-landing-question">Ask the catalog</label>
    <div><textarea id="assistant-landing-question" rows={2} maxLength={1000} value={question} disabled={disabled}
      placeholder={disabled ? chat.availability.reason ?? "The assistant is unavailable." : placeholder}
      title={disabled ? chat.availability.reason ?? "The assistant is unavailable." : "Press Tab to use the example question"}
      onChange={event => setQuestion(event.target.value)} onKeyDown={event => {
        if (event.nativeEvent.isComposing) return;
        if (event.key === "Tab" && !event.shiftKey && !question && !disabled) { event.preventDefault(); setQuestion(prompt); }
        if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); submit(); }
      }} />
      <button type="submit" disabled={disabled || !question.trim()}>Ask</button></div>
  </form>;
}
