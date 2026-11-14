import { useEffect, useState } from "react";
import { ASSISTANT_PROMPTS } from "./prompts";

// Adapted from FeedView's useRotatingChatPlaceholder; no upstream completion,
// mentions, model picker, or launch state is shared with this assistant.
export function useRotatingPlaceholder(active: boolean) {
  const [placeholder, setPlaceholder] = useState<string>(ASSISTANT_PROMPTS[0].slice(0, 1));
  const [index, setIndex] = useState(0);
  useEffect(() => {
    if (!active) return;
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches) {
      setPlaceholder(ASSISTANT_PROMPTS[0]); setIndex(0); return;
    }
    let index = 0, character = 1, erasing = false;
    let timer: number;
    setIndex(0); setPlaceholder(ASSISTANT_PROMPTS[0].slice(0, 1));
    const tick = () => {
      const prompt = ASSISTANT_PROMPTS[index];
      character += erasing ? -1 : 1;
      setPlaceholder(prompt.slice(0, character));
      let delay = erasing ? 25 : 45;
      if (character === prompt.length) { erasing = true; delay = 1800; }
      if (character === 0) { erasing = false; index = (index + 1) % ASSISTANT_PROMPTS.length; setIndex(index); delay = 350; }
      timer = window.setTimeout(tick, delay);
    };
    timer = window.setTimeout(tick, 45);
    return () => window.clearTimeout(timer);
  }, [active]);
  return { placeholder, prompt: ASSISTANT_PROMPTS[index] };
}
