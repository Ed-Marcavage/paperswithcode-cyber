import type { AssistantTopic } from "@/lib/api/assistant";

export function topicLabel(topics: AssistantTopic[], slug: string | null | undefined) {
  return slug ? topics.find(topic => topic.slug === slug)?.label ?? null : null;
}

/** "Penetration testing" -> "penetration testing"; leaves acronyms such as "AI-system security" alone. */
export function inSentence(label: string) {
  return /^[A-Z][a-z]/.test(label) ? label[0].toLowerCase() + label.slice(1) : label;
}
