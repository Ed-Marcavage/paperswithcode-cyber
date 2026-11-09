import type { MouseEvent } from "react";
import { pwcCliRepositoryUrl } from "@/lib/pwcCliRepository";
import { Link } from "react-router-dom";

import { AgentLogos } from "@/components/paper-detail/AgentLogos";
import { isDiscoveryCatalog } from "@/lib/apiUrl";

const icons: Record<string, string> = import.meta.env.PWC_PERSONAL_AGENT_ICONS ?? {};
const personalAgents = [
  { name: "OpenAI dots", icon: icons["dots.svg"] },
  { name: "Grok Bot", icon: icons["grok-bot.jpg"] },
  { name: "Muse", icon: icons["muse.svg"] },
];

interface McpShowcaseProps {
  className?: string;
  canNavigate?: () => boolean;
}

export function McpShowcase({ className = "", canNavigate }: McpShowcaseProps) {
  function handleNavigation(event: MouseEvent<HTMLAnchorElement>) {
    if (canNavigate && !canNavigate()) event.preventDefault();
  }

  return (
    <div className={`sidebar-section sidebar-section-tools ${className}`.trim()}>
      <div className="sidebar-label">Use PwC with your agent</div>
      {isDiscoveryCatalog() && (
        <Link to="/personal-agents" className="action-btn sidebar-tool-link sidebar-personal-agents"
          onClick={handleNavigation}>
          Personal agents
          <span className="inline-flex shrink-0 items-center gap-1.5" aria-hidden="true">
            {personalAgents.map(({ name, icon }) => (
              <img key={name} src={icon} alt="" title={name} width={18} height={18}
                className="h-[18px] w-[18px] rounded-sm object-contain" />
            ))}
          </span>
        </Link>
      )}
      <Link
        to="/mcp"
        className="action-btn sidebar-tool-link"
        title="Connect Claude, Codex, Cursor, or OpenCode to the PwC MCP server"
        onClick={handleNavigation}
      >
        MCP server
        <AgentLogos />
      </Link>
      <p className="sidebar-tools-copy">
        Search papers, benchmarks, and leaderboards from any MCP client, or from the
        terminal with the{" "}
        <a href={pwcCliRepositoryUrl} target="_blank" rel="noreferrer">
          <code>pwc</code> CLI
        </a>
        .
      </p>
    </div>
  );
}
