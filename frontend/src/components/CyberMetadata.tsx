import { useEffect, useRef } from "react";
import { useLocation } from "react-router-dom";
import { usePaper } from "@/hooks/usePapers";

const origin = import.meta.env.VITE_PUBLIC_SITE_URL || "https://paperswithcode-cyber.com";
const cyberDescription = "Explore cybersecurity papers, security agent harnesses, code and benchmarks. Browse reviewed research on penetration testing, vulnerability research and AI security.";

/** Keep initial server metadata accurate after client-side navigation. */
export function CyberMetadata() {
  const { pathname, search } = useLocation();
  const previous = useRef(pathname + search);
  const reference = /^\/paper\/([^/]+)$/.exec(pathname)?.[1];
  const paperQuery = usePaper(reference || "", Boolean(reference));
  const paper = paperQuery.data;
  useEffect(() => {
    if (previous.current !== pathname + search) {
      document.querySelectorAll('script[type="application/ld+json"]').forEach(node => node.remove());
      previous.current = pathname + search;
    }
    // Preserve the server's paper metadata while its cached API query loads.
    if (reference && paperQuery.isPending && document.querySelector('link[rel="canonical"]')?.getAttribute("href") === origin + pathname) return;
    let title = "Papers With Code Cyber";
    let description = cyberDescription;
    let path: string | undefined;
    let robots = "noindex,follow";
    const query = new URLSearchParams(search);
    if (pathname === "/") {
      title = "Security Agent Harnesses, Papers & Benchmarks | Papers With Code Cyber";
      path = "/";
      robots = query.has("start_date") || query.has("end_date") ? "noindex,follow" : "index,follow";
    } else if (pathname === "/catalog") {
      const canonical = new URLSearchParams();
      for (const key of ["topic", "target", "contribution", "kind", "year"]) {
        const value = query.get(key);
        if (value) canonical.set(key, value);
      }
      robots = canonical.size ? "noindex,follow" : "index,follow";
      const offset = Number(query.get("offset"));
      if (Number.isSafeInteger(offset) && offset > 0) canonical.set("offset", String(offset));
      path = "/catalog" + (canonical.size ? "?" + canonical.toString() : "");
      title = `Cybersecurity Research Catalog${offset > 0 ? ` — Page ${Math.floor(offset / 25) + 1}` : ""} | Papers With Code Cyber`;
      description = "Filter cybersecurity research by what it studies and what it contributes.";
    } else if (reference && paper) {
      path = "/paper/" + encodeURIComponent(paper.source === "arxiv" && paper.arxiv_id ? paper.arxiv_id : paper.id);
      title = paper.page_title || `${paper.title} | Papers With Code Cyber`;
      description = paper.tldr || paper.abstract || "Cybersecurity research and code.";
      robots = "index,follow";
    }
    document.title = title;
    for (const [selector, attribute, value] of [
      ['meta[name="description"]', "content", description],
      ['meta[name="robots"]', "content", robots],
      ['meta[property="og:title"]', "content", title],
      ['meta[property="og:description"]', "content", description],
      ['meta[property="og:url"]', "content", path ? origin + path : ""],
      ['meta[name="twitter:title"]', "content", title],
      ['meta[name="twitter:description"]', "content", description],
      ['meta[property="og:image"]', "content", reference && paper?.thumbnail_url ? new URL(paper.thumbnail_url, origin).href : origin + "/og-image.png?v=2"],
      ['meta[name="twitter:image"]', "content", reference && paper?.thumbnail_url ? new URL(paper.thumbnail_url, origin).href : origin + "/og-image.png?v=2"],
    ]) {
      let node = document.querySelector(selector);
      if (!node) {
        node = document.createElement("meta");
        const [, key, name] = /\[(\w+)="([^"]+)"\]/.exec(selector)!;
        node.setAttribute(key, name);
        document.head.append(node);
      }
      node.setAttribute(attribute, value);
    }
    document.querySelectorAll('link[rel="canonical"],link[rel="alternate"][type="text/markdown"]').forEach(node => node.remove());
    if (path) {
      const canonical = Object.assign(document.createElement("link"), { rel: "canonical", href: origin + path });
      const md = new URL(origin + path);
      md.pathname = path === "/" ? "/index.md" : md.pathname + ".md";
      document.head.append(canonical, Object.assign(document.createElement("link"), { rel: "alternate", type: "text/markdown", href: md.href }));
    }
  }, [pathname, search, reference, paper, paperQuery.isPending]);
  return null;
}
