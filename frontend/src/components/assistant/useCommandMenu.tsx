import { useEffect, useId, useRef, useState, type KeyboardEvent, type RefObject } from "react";
import type { AssistantSurface, AssistantTopic } from "@/lib/api/assistant";
import { assistantEvent } from "@/lib/catalogAnalytics";

interface Command { id: string; label: string; meta?: string; run: () => void }
interface CommandGroup { key: string; label: string; items: Command[] }

/**
 * The composer's "/" command list. The textarea keeps focus and its textbox role (a
 * textarea may not take the combobox role), and points at the active option with
 * aria-autocomplete and aria-activedescendant; a status line announces the list.
 * Built as groups of commands so more than "Topics" can be added later.
 */
export function useCommandMenu({ topics, draft, setDraft, onTopic, field, surface, enabled }: {
  topics: AssistantTopic[]; draft: string; setDraft: (value: string) => void; onTopic: (slug: string) => void;
  field: RefObject<HTMLTextAreaElement>; surface: AssistantSurface; enabled: boolean;
}) {
  const id = useId();
  const [browse, setBrowse] = useState(false); // opened from the "/" button, without slash text
  const [dismissed, setDismissed] = useState(false); // Escape closed it; stays closed until the slash text goes
  const [focused, setFocused] = useState(false);
  const [active, setActive] = useState(0);
  const slash = /^\/[^\n]*$/.test(draft) ? draft.slice(1) : null;
  if (dismissed && slash === null) setDismissed(false);
  const query = browse ? "" : slash ?? "";
  const needle = query.trim().toLowerCase();
  const close = () => { setBrowse(false); if (slash !== null) setDismissed(true); };
  const groups: CommandGroup[] = [{
    key: "topics", label: "Topics",
    items: topics.filter(topic => topic.label.toLowerCase().includes(needle)).map(topic => ({
      id: topic.slug, label: topic.label, meta: String(topic.count),
      run: () => { onTopic(topic.slug); if (!browse) setDraft(""); },
    })),
  }].filter(group => group.items.length);
  const items = groups.flatMap(group => group.items);
  // A slash followed by a sentence that matches nothing is a question, not a command.
  const wanted = browse || (slash !== null && !dismissed && (items.length > 0 || !/\s/.test(query)));
  const open = enabled && focused && topics.length > 0 && wanted;
  const index = Math.min(active, Math.max(items.length - 1, 0));
  const optionId = (item: Command) => `${id}-option-${item.id}`;

  useEffect(() => { setActive(0); }, [needle, browse]);
  const typed = useRef(draft);
  useEffect(() => { if (typed.current !== draft) { typed.current = draft; setBrowse(false); } }, [draft]);
  const reported = useRef(false);
  useEffect(() => {
    if (open && !reported.current) assistantEvent("slash_menu_used", surface);
    reported.current = open;
  }, [open, surface]);

  const choose = (item: Command) => { item.run(); setBrowse(false); setDismissed(false); field.current?.focus(); };
  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (!open || event.nativeEvent.isComposing) return false;
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (items.length) setActive((index + (event.key === "ArrowDown" ? 1 : items.length - 1)) % items.length);
      return true;
    }
    if ((event.key === "Enter" || event.key === "Tab") && !event.shiftKey && items.length) {
      event.preventDefault(); choose(items[index]); return true;
    }
    if (event.key === "Escape") { event.preventDefault(); close(); return true; }
    return false;
  };
  const status = !open ? "" : items.length ? `${items.length} ${items.length === 1 ? "topic" : "topics"}. Up and down arrows to move, Enter to choose, Escape to close.` : "No topics match.";
  return {
    open, onKeyDown,
    inputProps: {
      "aria-autocomplete": "list" as const,
      "aria-controls": open ? `${id}-list` : undefined,
      "aria-activedescendant": open && items.length ? optionId(items[index]) : undefined,
      onFocus: () => setFocused(true),
      onBlur: () => { setFocused(false); setBrowse(false); },
    },
    button: {
      expanded: open, controls: `${id}-list`,
      toggle: () => { if (open) close(); else { setDismissed(false); if (slash === null) setBrowse(true); } field.current?.focus(); setFocused(true); },
    },
    menu: open ? <div className="assistant-command-menu">
      <div id={`${id}-list`} role="listbox" aria-label="Commands">
        {groups.map(group => <div key={group.key} role="group" aria-labelledby={`${id}-${group.key}`}>
          <div id={`${id}-${group.key}`} role="presentation" className="assistant-command-heading">{group.label}</div>
          {group.items.map(item => {
            const selected = item === items[index];
            return <div key={item.id} id={optionId(item)} role="option" aria-selected={selected} className={selected ? "is-active" : undefined}
              onMouseDown={event => event.preventDefault()} onMouseMove={() => setActive(items.indexOf(item))} onClick={() => choose(item)}>
              <span>{item.label}</span>{item.meta && <span className="assistant-topic-count" aria-hidden="true">{item.meta}</span>}
            </div>;
          })}
        </div>)}
      </div>
      {!items.length && <p className="assistant-command-empty">No topic matches “{query.trim()}”.</p>}
    </div> : null,
    status: <span className="sr-only" role="status">{status}</span>,
  };
}
