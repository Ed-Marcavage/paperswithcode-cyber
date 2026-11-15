import type { AssistantToolStep } from "@/lib/api/assistant";

const labels: Record<string, string> = {
  search_papers: "Searched papers", browse_catalog: "Browsed the catalog", catalog_filters: "Checked catalog filters",
  get_paper_info: "Read paper details", list_developers: "Listed developers", get_developer: "Read developer details",
  list_organizations: "Listed organizations", get_organization: "Read organization details", list_recent_papers: "Checked recent papers",
  list_trending_papers: "Checked trending papers", get_related_papers: "Found related papers", read_paper: "Read a paper",
};
export function AssistantToolSteps({ steps, workingNote }: { steps: AssistantToolStep[]; workingNote?: string }) {
  if (!steps.length && !workingNote) return null;
  return <details className="assistant-tools"><summary>
    {workingNote || "Searched the catalog"}{steps.length > 0 && <> · {steps.length} {steps.length === 1 ? "step" : "steps"}</>}
  </summary>
    <ol>{steps.map((step, i) => <li key={`${step.call_id}-${i}`}>
      {labels[step.name] ?? "Catalog tool"}{step.pending ? "…" : step.error ? " — could not complete" : ""}
    </li>)}</ol>
  </details>;
}
