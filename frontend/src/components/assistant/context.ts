import { createContext, useContext } from "react";
import type { AssistantConversation, AssistantError, AssistantSurface, AssistantStatus } from "@/lib/api/assistant";

export interface AssistantContextValue {
  open: boolean; setOpen: (open: boolean) => void;
  conversation: AssistantConversation; currentId: string | null;
  draft: string; setDraft: (draft: string) => void;
  busy: boolean; loading: boolean; error: AssistantError | null;
  availability: AssistantStatus;
  launch: (question: string, path: string) => void;
  send: (question: string, surface: AssistantSurface, path: string) => Promise<void>;
  selectConversation: (id: string) => void; newChat: (surface?: AssistantSurface) => void; stop: () => void;
}
export const AssistantContext = createContext<AssistantContextValue | null>(null);
export function useAssistant() {
  const value = useContext(AssistantContext);
  if (!value) throw new Error("AssistantProvider is missing");
  return value;
}
