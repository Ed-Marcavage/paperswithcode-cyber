import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Link } from "react-router-dom";
import { allowedLink, chatUrlTransform, withholdPartialCitation } from "./markdown";
import { assistantEvent } from "@/lib/catalogAnalytics";
import type { AssistantSurface } from "@/lib/api/assistant";

export function AssistantMarkdown({ text, streaming, evidence, surface = "panel" }: { text: string; streaming: boolean; evidence: Set<string>; surface?: AssistantSurface }) {
  return <div className="assistant-markdown"><ReactMarkdown skipHtml remarkPlugins={[remarkGfm]} urlTransform={chatUrlTransform}
    components={{
      img: () => null,
      a: ({ href, children }) => {
        const link = allowedLink(href ?? "", evidence);
        if (!link) return <span>{children}</span>;
        const clicked = () => assistantEvent("link_clicked", surface);
        return link.local ? <Link to={link.href} onClick={clicked}>{children}</Link> : <a href={link.href} rel="noreferrer" onClick={clicked}>{children}</a>;
      },
    }}>{streaming ? withholdPartialCitation(text) : text}</ReactMarkdown></div>;
}
