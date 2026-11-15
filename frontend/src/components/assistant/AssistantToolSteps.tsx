import { useId, useState } from "react";
import type { AssistantToolStep } from "@/lib/api/assistant";
import { AssistantIcon } from "./icons";

const labels: Record<string, string> = {
  search_papers: "Searched papers", browse_catalog: "Browsed the catalog", catalog_filters: "Checked catalog filters",
  get_paper_info: "Read paper details", list_developers: "Listed developers", get_developer: "Read developer details",
  list_organizations: "Listed organizations", get_organization: "Read organization details", list_recent_papers: "Checked recent papers",
  list_trending_papers: "Checked trending papers", get_related_papers: "Found related papers", read_paper: "Read a paper",
};
// What a step is doing while it runs, for the live working line.
const active: Record<string, string> = {
  search_papers: "Searching papers", browse_catalog: "Browsing the catalog", catalog_filters: "Checking catalog filters",
  get_paper_info: "Reading paper details", list_developers: "Listing developers", get_developer: "Reading developer details",
  list_organizations: "Listing organizations", get_organization: "Reading organization details", list_recent_papers: "Checking recent papers",
  list_trending_papers: "Checking trending papers", get_related_papers: "Finding related papers", read_paper: "Reading a paper",
};

function activity(steps: AssistantToolStep[], workingNote: string | undefined, writing: boolean) {
  if (workingNote) return workingNote.replace(/[.…\s]+$/, "") + "…";
  const pending = [...steps].reverse().find(step => step.pending);
  if (pending) return `${active[pending.name] ?? "Searching the catalog"}…`;
  return writing ? "Writing the answer…" : steps.length ? "Reading the results…" : "Thinking…";
}

/**
 * One quiet row under an answer. While the answer runs it shows a small pulse and
 * the latest thing the assistant is doing; afterwards it summarises the catalog
 * steps and expands to list them.
 */
export function AssistantToolSteps({ steps, workingNote, running = false, writing = false }:
  { steps: AssistantToolStep[]; workingNote?: string; running?: boolean; writing?: boolean }) {
  const [open, setOpen] = useState(false);
  const listId = useId();
  if (!running && !steps.length && !workingNote) return null;
  const count = steps.length > 0 ? ` · ${steps.length} ${steps.length === 1 ? "step" : "steps"}` : "";
  const label = running ? activity(steps, workingNote, writing) : `${workingNote || "Searched the catalog"}${count}`;
  return <div className={`assistant-tools${running ? " is-running" : ""}`}>
    <div className="assistant-tools-row">
      {running && <span className="assistant-pulse" aria-hidden="true"><i /><i /><i /></span>}
      {steps.length > 0 ? <button type="button" className="assistant-tools-toggle" aria-expanded={open} aria-controls={listId} onClick={() => setOpen(!open)}>
        <span role={running ? "status" : undefined} className="assistant-tools-label">{label}</span>
        {running && <span className="assistant-tools-count">{count}</span>}
        <AssistantIcon name="chevron" size={12} />
      </button> : <span role="status" className="assistant-tools-label">{label}</span>}
    </div>
    {open && steps.length > 0 && <ol id={listId}>{steps.map((step, i) => <li key={`${step.call_id}-${i}`} className={step.error ? "is-error" : step.pending ? "is-pending" : undefined}>
      {labels[step.name] ?? "Catalog tool"}{step.pending ? "…" : step.error ? " (could not complete)" : ""}
    </li>)}</ol>}
  </div>;
}
