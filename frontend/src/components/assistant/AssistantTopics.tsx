import { useId } from "react";
import type { AssistantTopic } from "@/lib/api/assistant";
import { AssistantIcon } from "./icons";

const entries = (count: number) => `${count} ${count === 1 ? "entry" : "entries"}`;

/** One chip per topic, in the order the endpoint returns; the chosen one is pressed. */
export function TopicChips({ topics, selected, onSelect, disabled = false }:
  { topics: AssistantTopic[]; selected: string | null; onSelect: (slug: string | null) => void; disabled?: boolean }) {
  const label = useId();
  if (!topics.length) return null;
  return <div className="assistant-topics">
    <div id={label} className="assistant-topics-label">Or pick a topic, then ask your own question</div>
    <div className="assistant-topic-chips" role="group" aria-labelledby={label}>
      {topics.map(topic => <button key={topic.slug} type="button" aria-pressed={selected === topic.slug} disabled={disabled}
        title={`${entries(topic.count)} in the catalog`} onClick={() => onSelect(selected === topic.slug ? null : topic.slug)}>
        <span>{topic.label}</span><span className="assistant-topic-count" aria-hidden="true">{topic.count}</span>
        <span className="sr-only">, {entries(topic.count)}</span>
      </button>)}
    </div>
  </div>;
}

/** The chosen topic, shown on the composer until it is removed. */
export function TopicTag({ label, onRemove }: { label: string; onRemove: () => void }) {
  return <div className="assistant-topic-tag-row">
    <span className="assistant-topic-tag">
      <span className="assistant-topic-tag-key">Topic</span>
      <span className="assistant-topic-tag-label">{label}</span>
      <button type="button" aria-label={`Remove topic ${label}`} title="Remove topic" onClick={onRemove}><AssistantIcon name="close" size={11} /></button>
    </span>
  </div>;
}

/** Opens the command list without the slash key, for touch keyboards and pointer users. */
export function TopicButton({ expanded, controls, toggle, disabled }: { expanded: boolean; controls: string; toggle: () => void; disabled?: boolean }) {
  return <button type="button" className="assistant-topic-button" aria-label="Topics" title="Topics (type /)" aria-haspopup="listbox"
    aria-expanded={expanded} aria-controls={expanded ? controls : undefined} disabled={disabled}
    onMouseDown={event => event.preventDefault()} onClick={toggle}><span aria-hidden="true">/</span></button>;
}
