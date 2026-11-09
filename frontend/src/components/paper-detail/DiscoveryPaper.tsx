import { useEffect, useRef } from "react";
import { externalResource, paperOpened, resourceClicked, taxonomySelected } from "@/lib/catalogAnalytics";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { axes, type Axis, discoveryPaperQuery, filtersQuery } from "@/lib/api/discovery";
import { apiUrl } from "@/lib/apiUrl";
import "@/views/DiscoveryCatalog.css";

export function DiscoveryPaper({ paperId }: { paperId: string }) {
  const { data: paper, isError } = useQuery(discoveryPaperQuery(paperId));
  const terms = useQuery(filtersQuery);
  const lastOpen = useRef<string>();
  useEffect(() => {
    if (paper && lastOpen.current !== paper.paper_id) {
      paperOpened(paper);
      lastOpen.current = paper.paper_id;
    }
  }, [paper]);
  if (!paper) return <p role="status">{isError ? "Catalog details unavailable." : "Loading catalog details…"}</p>;
  const kind = paper.facets.kind?.[0];
  return <section className="discovery-paper" aria-label="Catalog details">
    <h2>Catalog details</h2>
    <dl>{(Object.keys(axes) as Axis[]).filter(axis => paper.facets[axis]?.length).map(axis =>
      <div key={axis} style={{display:"contents"}}><dt>{axes[axis]}</dt><dd>{paper.facets[axis]?.map(value =>
        <Link key={value} onClick={() => taxonomySelected(axis, value, "paper_tag")} to={"/catalog?" + new URLSearchParams({[axis]:value})}>{terms.data?.[axis]?.[value] || value}</Link>)}</dd></div>
    )}</dl>
    <div className="discovery-resources">
      {paper.artifact_url && <a onClick={() => resourceClicked(paper.paper_id, externalResource(paper.artifact_url!, "artifact"))} href={paper.artifact_url} target="_blank" rel="noreferrer">Open project artifact ↗</a>}
      {paper.has_text
        ? <a onClick={() => resourceClicked(paper.paper_id, "cached_text")} href={apiUrl("/api/v1/catalog/papers/" + encodeURIComponent(paper.paper_id) + "/text")}>Read cached text</a>
        : <span>{kind === "paper" && "No cached text. "}<a onClick={() => resourceClicked(paper.paper_id, externalResource(paper.source_url, "source"))} href={paper.source_url} target="_blank" rel="noreferrer">{kind === "post" ? "Read original post" : kind === "repository" ? "View original repository" : "Read at source"} ↗</a></span>}
    </div>
  </section>;
}
