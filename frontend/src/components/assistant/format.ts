import { useLayoutEffect, type RefObject } from "react";
import { useLocation } from "react-router-dom";

/** The chat page is the conversation, so the panel and its trigger stand down there. */
export function useOnChatPage() {
  return /^\/chat(\/|$)/.test(useLocation().pathname);
}

/** Set on <html> while the panel is open, so wide layouts make room for it. */
export const PANEL_OPEN_CLASS = "assistant-panel-open";

/** "Today", "Yesterday", "Nov 12", or "Nov 12, 2025" outside the current year. */
export function friendlyDate(value: string, now = new Date()): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const day = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const days = Math.round((day(now) - day(date)) / 86_400_000);
  if (days === 0) return "Today";
  if (days === 1) return "Yesterday";
  return date.toLocaleDateString("en-US", { month: "short", day: "numeric",
    ...(date.getFullYear() === now.getFullYear() ? {} : { year: "numeric" }) });
}

/**
 * Grows a textarea with its content up to `max` pixels, then scrolls inside it.
 * `floor` lists texts (such as rotating placeholders) whose height the box should
 * reserve while it is empty, so a wrapping placeholder never jumps or clips;
 * `centre` is the placeholder currently shown, centred vertically in that space.
 */
export function useAutosize(ref: RefObject<HTMLTextAreaElement>, value: string, max: number, floor: readonly string[] = [], centre?: string) {
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const resize = () => {
      el.style.paddingTop = ""; el.style.paddingBottom = "";
      el.style.height = "auto";
      let height = el.scrollHeight;
      if (!value && floor.length) {
        const shown = el.placeholder;
        const measure = (text: string) => { el.placeholder = text; return el.scrollHeight; };
        for (const text of floor) height = Math.max(height, measure(text));
        const own = centre ? measure(centre) : height;
        el.placeholder = shown;
        const extra = Math.max(0, Math.min(height, max) - own) / 2;
        if (extra > 0) {
          const style = getComputedStyle(el);
          el.style.paddingTop = `${parseFloat(style.paddingTop) + extra}px`;
          el.style.paddingBottom = `${parseFloat(style.paddingBottom) + extra}px`;
        }
      }
      if (height > 0) el.style.height = `${Math.min(height, max)}px`;
      el.style.overflowY = height > max ? "auto" : "hidden";
    };
    resize();
    window.addEventListener("resize", resize);
    return () => window.removeEventListener("resize", resize);
  }, [ref, value, max, floor, centre]);
}
