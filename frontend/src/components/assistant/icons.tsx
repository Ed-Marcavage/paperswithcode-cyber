import type { ReactNode } from "react";

// Same drawing rules as the header icons: 16px grid, 1.5px strokes, round caps.
const paths = {
  send: <path d="M8 13V3M3.5 7.5L8 3l4.5 4.5" />,
  stop: <rect x="4" y="4" width="8" height="8" rx="1.5" fill="currentColor" stroke="none" />,
  plus: <path d="M8 3v10M3 8h10" />,
  close: <path d="M4 4l8 8M12 4l-8 8" />,
  chats: <path d="M2.5 4h11M2.5 8h11M2.5 12h7" />,
  external: <path d="M9.5 2.5h4v4M13.5 2.5L8 8M11.5 9.5v4h-9v-9h4" />,
  expand: <path d="M9.5 2.5h4v4M13.5 2.5L9 7M6.5 13.5h-4v-4M2.5 13.5L7 9" />,
  pencil: <path d="M10.5 3l2.5 2.5L6 12.5H3.5V10L10.5 3z" />,
  trash: <path d="M3 4.5h10M6.5 4.5V3h3v1.5M4.5 4.5l.6 8.5h5.8l.6-8.5" />,
  chevron: <path d="M6 4l4 4-4 4" />,
  ask: <path d="M3 3.5h10v7H7.5L4.5 13v-2.5H3z" />,
  thumbUp: <path d="M5 7v6.5H2.5V7H5zm0 0l2.5-4.5c1 0 1.5.7 1.5 1.6V6h3.4c.7 0 1.2.6 1.1 1.3l-.8 4.8c-.1.8-.8 1.4-1.6 1.4H5" />,
  thumbDown: <path d="M5 9V2.5H2.5V9H5zm0 0l2.5 4.5c1 0 1.5-.7 1.5-1.6V10h3.4c.7 0 1.2-.6 1.1-1.3l-.8-4.8c-.1-.8-.8-1.4-1.6-1.4H5" />,
} satisfies Record<string, ReactNode>;

export type AssistantIconName = keyof typeof paths;

export function AssistantIcon({ name, size = 16 }: { name: AssistantIconName; size?: number }) {
  return <svg className="assistant-icon" viewBox="0 0 16 16" width={size} height={size} aria-hidden="true" focusable="false"
    fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">{paths[name]}</svg>;
}
