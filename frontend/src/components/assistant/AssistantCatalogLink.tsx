import { Link } from "react-router-dom";
import { useAssistant } from "./context";

/**
 * A quiet "Try chat" offer beside hand-filtering. Wider screens open the Ask
 * panel in place so the catalog stays visible, and a second click closes it
 * again ("Close chat", `aria-expanded`); phones go to the chat page, where the
 * conversation has the whole screen. Hidden while the assistant is unavailable.
 */
export function AssistantCatalogLink({ className = "" }: { className?: string }) {
  const { availability, open, setOpen } = useAssistant();
  if (!availability.available) return null;
  return <Link to="/chat" className={`assistant-catalog-link ${className}`}
    title={open ? "Close the Ask panel" : "Ask the assistant instead of filtering by hand"}
    aria-expanded={open} aria-controls="assistant-panel"
    onClick={event => {
      if (window.matchMedia?.("(max-width: 640px)")?.matches || event.metaKey || event.ctrlKey || event.shiftKey) return;
      event.preventDefault();
      setOpen(!open);
    }}>{open ? <>Close chat<span aria-hidden="true"> ×</span></> : <>Try chat<span aria-hidden="true"> →</span></>}</Link>;
}
