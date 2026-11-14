import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Link } from "react-router-dom";
import { allowedLink, chatUrlTransform, withholdPartialCitation } from "./markdown";

export function AssistantMarkdown({ text, streaming, evidence }: { text: string; streaming: boolean; evidence: Set<string> }) {
  return <div className="assistant-markdown"><ReactMarkdown skipHtml remarkPlugins={[remarkGfm]} urlTransform={chatUrlTransform}
    components={{
      img: () => null,
      a: ({ href, children }) => {
        const link = allowedLink(href ?? "", evidence);
        if (!link) return <span>{children}</span>;
        return link.local ? <Link to={link.href}>{children}</Link> : <a href={link.href} rel="noreferrer">{children}</a>;
      },
    }}>{streaming ? withholdPartialCitation(text) : text}</ReactMarkdown></div>;
}
