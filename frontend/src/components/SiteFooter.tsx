import { Link, useLocation } from "react-router-dom";

import { isDiscoveryCatalog } from "@/lib/apiUrl";

const SiteFooter = () => {
  const { pathname } = useLocation();

  if (pathname === "/chat" || pathname.startsWith("/chat/") || pathname.startsWith("/pdf/")) return null;

  return (
    <footer className="site-footer">
      <div className="site-footer-inner">
        <span>{isDiscoveryCatalog() ? "Cyberintel research catalog · Built on Papers With Code" : `© ${new Date().getFullYear()} Hugging Face`}</span>
        <Link to="/docs/api">API</Link>
        <Link to="/mcp">MCP</Link>
        <Link to="/privacy">Privacy</Link>
        {!isDiscoveryCatalog() && <>
        <a
          href="https://github.com/huggingface/paperswithcode-feedback/issues"
          target="_blank"
          rel="noreferrer"
        >
          Feedback
        </a>
        </>}
      </div>
    </footer>
  );
};

export default SiteFooter;
