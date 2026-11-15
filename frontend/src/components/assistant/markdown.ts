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

// Links to the public site in an answer stay in the app, like links to this origin.
const CATALOG_ORIGIN = "https://paperswithcode-cyber.com";
const unsafeCharacter = (value: string) => value.includes("\\") || [...value].some(c => c.charCodeAt(0) <= 32 || c.charCodeAt(0) === 127);

/**
 * The destination a link in an answer may have, or null to render plain text. Site links
 * (a path, this origin or the public catalog) become a router path that is checked after
 * normalisation, so dot segments or encoded slashes can never turn it into a
 * protocol-relative address that leaves the site. Other http(s) links are allowed only when
 * that exact address appeared in a tool result (`evidence`); they open in a new tab.
 */
export function allowedLink(href: string, evidence: Set<string>): { href: string; local: boolean } | null {
  if (!href || href.startsWith("//") || unsafeCharacter(href)) return null;
  const origin = window.location.origin;
  let url: URL;
  try { url = new URL(href, origin); } catch { return null; }
  if (!["http:", "https:"].includes(url.protocol) || url.username || url.password) return null;
  const localPath = href.startsWith("/");
  // A bare word such as "catalog_url_placeholder" resolves against this page; it is not a link.
  if (!localPath && !/^https?:\/\//i.test(href)) return null;
  if (localPath || url.origin === origin || url.origin === CATALOG_ORIGIN) {
    const path = url.pathname + url.search + url.hash;
    let decoded: string;
    try { decoded = decodeURIComponent(url.pathname); } catch { return null; }
    if (!path.startsWith("/") || path.startsWith("//") || decoded.startsWith("//") || unsafeCharacter(decoded)) return null;
    if (new URL(path, origin).origin !== origin) return null;
    return { href: path, local: true };
  }
  return evidence.has(href) ? { href, local: false } : null;
}
