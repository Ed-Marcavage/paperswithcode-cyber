import { defaultUrlTransform } from "react-markdown";
import type { AssistantMessage } from "@/lib/api/assistant";

// Adapted from the named helpers in chat/ChatMarkdown.tsx. The assistant
// uses real catalog addresses, so upstream's custom citation schemes stay off.
export function withholdPartialCitation(text: string): string {
  const open = text.lastIndexOf("[");
  if (open === -1) return text;
  const tail = text.slice(open);
  if (/^\[[^\]]*(\]\(?[^)\s]*)?$/.test(tail)) return text.slice(0, open);
  return text;
}
export const chatUrlTransform = (url: string): string => defaultUrlTransform(url);

export function evidenceLinks(messages: AssistantMessage[]): Set<string> {
  const links = new Set<string>();
  for (const message of messages) for (const step of message.tool_steps) {
    for (const match of (step.result ?? "").matchAll(/https?:\/\/[^\s<>"\\]+/g)) {
      links.add(match[0].replace(/[.,;:)\]}]+$/, ""));
    }
  }
  return links;
}

export function allowedLink(href: string, evidence: Set<string>): { href: string; local: boolean } | null {
  if (!href || href.startsWith("//") || href.includes("\\") || [...href].some(c => c.charCodeAt(0) <= 32 || c.charCodeAt(0) === 127)) return null;
  const origin = window.location.origin;
  try {
    const url = new URL(href, origin);
    if (!["http:", "https:"].includes(url.protocol) || url.username || url.password) return null;
    const localPath = href.startsWith("/") && !href.startsWith("//");
    // A bare word such as "catalog_url_placeholder" resolves against this page; it is not a link.
    if (!localPath && !/^https?:\/\//i.test(href)) return null;
    const sameOrigin = url.origin === origin;
    if (!localPath && !sameOrigin && !evidence.has(href)) return null;
    const catalog = url.origin === "https://paperswithcode-cyber.com";
    return { href: sameOrigin || catalog ? url.pathname + url.search + url.hash : href, local: sameOrigin || catalog };
  } catch { return null; }
}
