import { createContext, useContext } from "react";
import type { AssistantConversation, AssistantError, AssistantSurface, AssistantStatus, AssistantTopic } from "@/lib/api/assistant";

export interface AssistantContextValue {
  open: boolean; setOpen: (open: boolean) => void;
  conversation: AssistantConversation; currentId: string | null;
  draft: string; setDraft: (draft: string) => void;
  busy: boolean; loading: boolean; error: AssistantError | null;
  availability: AssistantStatus;
  launch: (question: string, path: string, topic?: string | null) => void;
  /** keepDraft: a follow-up click leaves what the visitor was typing; topic overrides the chat's topic. */
  send: (question: string, surface: AssistantSurface, path: string, options?: { keepDraft?: boolean; topic?: string | null }) => Promise<void>;
  /** Topics from the endpoint (empty when it fails); the current chat's topic slug and its setter. */
  topics: AssistantTopic[]; topic: string | null; setTopic: (slug: string | null, surface?: AssistantSurface) => void;
  selectConversation: (id: string) => void; newChat: (surface?: AssistantSurface) => void; stop: () => void;
}
export const AssistantContext = createContext<AssistantContextValue | null>(null);
export function useAssistant() {
  const value = useContext(AssistantContext);
  if (!value) throw new Error("AssistantProvider is missing");
  return value;
}
