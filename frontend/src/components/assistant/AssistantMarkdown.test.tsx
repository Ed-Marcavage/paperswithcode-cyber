import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { expect, it } from "vitest";
import { AssistantMarkdown } from "./AssistantMarkdown";
import { AssistantToolSteps } from "./AssistantToolSteps";
import { allowedLink, evidenceLinks, withholdPartialCitation } from "./markdown";

it("renders only safe evidence or site links, with no HTML or images", () => {
  const evidence = evidenceLinks([{ id: "a", role: "assistant", status: "done", content: "", tool_steps: [
    { name: "browse_catalog", result: '{"url":"https://example.com/evidence"}' },
  ] }]);
  const { container } = render(<MemoryRouter><AssistantMarkdown streaming={false} evidence={evidence}
    text={'<img src="x" onerror="alert(1)">\n\n![hidden](https://example.com/a.png) **Safe** [proof](https://example.com/evidence) [made up](https://unknown.test/) [bad](javascript:alert%281%29) [org](/orgs/alpha)'} /></MemoryRouter>);
  expect(container.querySelectorAll("img")).toHaveLength(0);
  expect(screen.getByText("Safe").tagName).toBe("STRONG");
  expect(screen.getAllByRole("link")).toHaveLength(2);
  expect(screen.getByRole("link", { name: "proof (opens in a new tab)" })).toHaveAttribute("href", "https://example.com/evidence");
  for (const href of ["//evil.test", "/\\evil.test", "javascript:alert(1)", "data:text/html,x", "https://u:p@example.com"]) {
    expect(allowedLink(href, new Set([href]))).toBeNull();
  }
});
it("withholds unfinished citations and navigates catalog links with the router", () => {
  expect(withholdPartialCitation("Read [paper](/paper/one")).toBe("Read ");
  const { rerender } = render(<MemoryRouter><AssistantMarkdown streaming evidence={new Set()} text="Read [paper](/paper/one" /></MemoryRouter>);
  expect(screen.queryByRole("link")).toBeNull();
  rerender(<MemoryRouter><AssistantMarkdown streaming evidence={new Set(["https://paperswithcode-cyber.com/paper/one"])}
    text="Read [paper](https://paperswithcode-cyber.com/paper/one)" />
    <Routes><Route path="/paper/one" element={<p>Paper destination</p>} /><Route path="*" element={null} /></Routes></MemoryRouter>);
  fireEvent.click(screen.getByRole("link"));
  expect(screen.getByText("Paper destination")).toBeInTheDocument();
  expect(screen.getByText("Read", { exact: false })).toBeInTheDocument();
});
it("keeps tool details collapsed by default and expands them from a quiet row", () => {
  const { container } = render(<AssistantToolSteps steps={[{ name: "search_papers" }, { name: "get_paper_info" }, { name: "read_paper", error: true }]} />);
  expect(screen.getByText("Searched the catalog · 3 steps")).toBeInTheDocument();
  const toggle = screen.getByRole("button", { name: /Searched the catalog/ });
  expect(toggle).toHaveAttribute("aria-expanded", "false");
  expect(container.querySelector("ol")).toBeNull();
  fireEvent.click(toggle);
  expect(toggle).toHaveAttribute("aria-expanded", "true");
  expect(screen.getByText("Read a paper (could not complete)")).toBeInTheDocument();
});
it("shows a working state at once, then the latest tool or working note", () => {
  const { rerender } = render(<AssistantToolSteps steps={[]} running />);
  expect(screen.getByRole("status")).toHaveTextContent("Thinking…");
  rerender(<AssistantToolSteps steps={[{ name: "search_papers", call_id: "a", pending: true }]} running />);
  expect(screen.getByRole("status")).toHaveTextContent("Searching papers…");
  rerender(<AssistantToolSteps steps={[{ name: "search_papers", call_id: "a", pending: true }]} workingNote="Checking the industry posts." running />);
  expect(screen.getByRole("status")).toHaveTextContent("Checking the industry posts…");
  rerender(<AssistantToolSteps steps={[{ name: "search_papers", call_id: "a" }]} running writing />);
  expect(screen.getByRole("status")).toHaveTextContent("Writing the answer…");
  rerender(<AssistantToolSteps steps={[{ name: "search_papers", call_id: "a" }]} />);
  expect(screen.queryByRole("status")).toBeNull();
  expect(screen.getByText("Searched the catalog · 1 step")).toBeInTheDocument();
});

it("does not turn a bare word or relative path into a link", () => {
  for (const href of ["catalog_url_placeholder", "paper/123", "./paper/123"]) {
    expect(allowedLink(href, new Set())).toBeNull();
  }
  expect(allowedLink("/paper/123", new Set())).toEqual({ href: "/paper/123", local: true });
});

it("opens evidence links off the site in a new tab with an indicator, and site links through the router", () => {
  const external = "https://shopify.engineering/cyber-chaos-monkey";
  render(<MemoryRouter initialEntries={["/catalog"]}>
    <AssistantMarkdown streaming={false} evidence={new Set([external])}
      text={`See [Cyber Chaos Monkey](${external}) and [the catalog](/catalog?kind=post) or [Wiz](https://paperswithcode-cyber.com/paper/1012).`} />
    <Routes><Route path="/paper/1012" element={<p>Wiz page</p>} /><Route path="*" element={null} /></Routes>
  </MemoryRouter>);
  const out = screen.getByRole("link", { name: /Cyber Chaos Monkey/ });
  expect(out).toHaveAttribute("href", external);
  expect(out).toHaveAttribute("target", "_blank");
  expect(out).toHaveAttribute("rel", "noopener noreferrer");
  expect(out).toHaveAccessibleName("Cyber Chaos Monkey (opens in a new tab)");
  expect(out.querySelector("svg.assistant-icon")).not.toBeNull();
  for (const name of ["the catalog", "Wiz"]) {
    const link = screen.getByRole("link", { name });
    expect(link).not.toHaveAttribute("target");
    expect(link.querySelector("svg")).toBeNull();
  }
  expect(screen.getByRole("link", { name: "Wiz" })).toHaveAttribute("href", "/paper/1012");
  expect(screen.getByRole("link", { name: "the catalog" })).toHaveAttribute("href", "/catalog?kind=post");
});

it("never turns a site link into one that leaves the site after normalisation", () => {
  for (const href of ["/.//evil.test/x", "/..//evil.test", "/%2F/evil.test", "/%2f%2fevil.test", "/\\evil.test", "//evil.test",
    "/%5Cevil.test", "https://paperswithcode-cyber.com/.//evil.test/collect?x=1", `${window.location.origin}/..//evil.test`]) {
    expect(allowedLink(href, new Set([href]))).toBeNull();
  }
  expect(allowedLink("/paper/123", new Set())).toEqual({ href: "/paper/123", local: true });
  expect(allowedLink("/catalog?kind=post#top", new Set())).toEqual({ href: "/catalog?kind=post#top", local: true });
  expect(allowedLink("/orgs/./alpha", new Set())).toEqual({ href: "/orgs/alpha", local: true });
  expect(allowedLink("https://paperswithcode-cyber.com/paper/1", new Set())).toEqual({ href: "/paper/1", local: true });
  expect(allowedLink(`${window.location.origin}/paper/2`, new Set())).toEqual({ href: "/paper/2", local: true });
  // Off-site links still need their exact address in a tool result.
  expect(allowedLink("https://evil.test/x", new Set())).toBeNull();
  expect(allowedLink("https://example.com/evidence", new Set(["https://example.com/evidence"]))).toEqual({ href: "https://example.com/evidence", local: false });
});
