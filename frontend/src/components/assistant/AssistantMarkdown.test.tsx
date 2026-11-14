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
  expect(screen.getByRole("link", { name: "proof" })).toHaveAttribute("href", "https://example.com/evidence");
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
it("keeps tool details collapsed by default", () => {
  const { container } = render(<AssistantToolSteps steps={[{ name: "search_papers" }, { name: "get_paper_info" }, { name: "read_paper", error: true }]} />);
  expect(screen.getByText("Searched the catalog · 3 steps")).toBeInTheDocument();
  expect(container.querySelector("details")).not.toHaveAttribute("open");
});
