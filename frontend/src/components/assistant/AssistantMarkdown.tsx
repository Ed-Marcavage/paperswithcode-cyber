import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Link } from "react-router-dom";
import { allowedLink, chatUrlTransform, linkBareCatalogPaths, withholdPartialCitation } from "./markdown";
import { assistantEvent } from "@/lib/catalogAnalytics";
import { AssistantIcon } from "./icons";
import type { AssistantSurface } from "@/lib/api/assistant";

export function AssistantMarkdown({ text, streaming, evidence, surface = "panel" }: { text: string; streaming: boolean; evidence: Set<string>; surface?: AssistantSurface }) {
  return <div className="assistant-markdown"><ReactMarkdown skipHtml remarkPlugins={[remarkGfm]} urlTransform={chatUrlTransform}
    components={{
      img: () => null,
      // Wide answer tables scroll inside their own frame instead of widening the column.
      table: ({ children }) => <div className="assistant-table" tabIndex={0} role="region" aria-label="Table"><table>{children}</table></div>,
      a: ({ href, children }) => {
        const link = allowedLink(href ?? "", evidence);
        if (!link) return <span>{children}</span>;
        const clicked = () => assistantEvent("link_clicked", surface, { link: link.local ? "site" : "external" });
        // Site pages open through the router, so the panel stays open; anything else opens in a new tab.
        if (link.local) return <Link to={link.href} onClick={clicked}>{children}</Link>;
        return <a href={link.href} target="_blank" rel="noopener noreferrer" className="assistant-external-link" onClick={clicked}>
          {children}<AssistantIcon name="external" size={11} /><span className="sr-only"> (opens in a new tab)</span>
        </a>;
      },
    }}>{linkBareCatalogPaths(streaming ? withholdPartialCitation(text) : text)}</ReactMarkdown></div>;
}
