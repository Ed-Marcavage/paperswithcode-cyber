import { useRef, useState } from "react";
import { Check, Copy } from "lucide-react";

import { useDocumentTitle } from "@/hooks/useDocumentTitle";
import { formatPageTitle } from "@/lib/latexPlainText";
import "./PersonalAgentsView.css";

const prompt = `Pick one cybersecurity paper, blog or repo for me every morning based on what you know about what I’m building, researching, or learning. Give me the first pick now.

Use the Papers With Code Cyber catalog. Connect to its public MCP at https://paperswithcode-cyber.com/mcp. If you can’t use MCP, browse https://paperswithcode-cyber.com/api/v1/catalog/papers?kind=paper. Neither requires an API key.

Choose a paper you haven’t sent me before. Favor relevance over recency. Start with one sentence explaining why you picked it for me. Then tell me what the authors tried, what they found, one limitation, and one idea I could test in my own work. Read the original when available, and say if you only had the abstract.

Link to the catalog entry, the original paper, and the authors’ code when available.

If you have a feature request or bug fix, please submit an issue, both the MCP and website are OSS below:
- https://github.com/Ed-Marcavage/pwc-cli
- https://github.com/Ed-Marcavage/paperswithcode`;

export default function PersonalAgentsView() {
  useDocumentTitle(formatPageTitle("Personal agents"));
  const promptBody = useRef<HTMLDivElement>(null);
  const [status, setStatus] = useState<"idle" | "copied" | "manual">("idle");

  async function copyPrompt() {
    try {
      await navigator.clipboard.writeText(prompt);
      setStatus("copied");
    } catch {
      if (promptBody.current) window.getSelection()?.selectAllChildren(promptBody.current);
      setStatus("manual");
    }
  }

  return (
    <article className="page personal-agents-page">
      <header className="feed-header">
        <div>
          <h1 className="feed-title">Personal <em>agents</em></h1>
          <p className="feed-subtitle">Paste this prompt into your personal agent for a daily paper pick.</p>
        </div>
      </header>
      <section className="agent-prompt" aria-labelledby="agent-prompt-title">
        <div className="agent-prompt-heading">
          <h2 id="agent-prompt-title">Daily paper prompt</h2>
          <button className="action-btn" type="button" onClick={copyPrompt}>
            {status === "copied" ? <Check size={15} aria-hidden /> : <Copy size={15} aria-hidden />}
            <span aria-live="polite">{status === "copied" ? "Copied" : "Copy prompt"}</span>
          </button>
        </div>
        <div ref={promptBody} className="agent-prompt-body">
          {prompt.split("\n\n").map(paragraph => <p key={paragraph}>{paragraph}</p>)}
        </div>
        {status === "manual" && <p role="status">Use your device’s Copy command to copy the selected prompt.</p>}
      </section>
    </article>
  );
}
