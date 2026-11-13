import { useEffect, useRef } from "react";
import { externalResource, paperOpened, resourceClicked, taxonomySelected } from "@/lib/catalogAnalytics";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { axes, type Axis, discoveryPaperQuery, filtersQuery } from "@/lib/api/discovery";
import { apiUrl } from "@/lib/apiUrl";
import { postTypeLabel, subtopicLabel } from "@/lib/industryPost";
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
  const post = kind === "post" ? paper.post : null;
  const flags = post ? [
    post.reports_benchmark_results && "Reports benchmark results",
    post.agent_harness_engineering && "Agent harness engineering",
  ].filter(Boolean) : [];
  return <section className="discovery-paper" aria-label="Catalog details">
    <h2>Catalog details</h2>
    {post && <p className="tldr-box discovery-post-tldr">{post.tldr}</p>}
    <dl>{(Object.keys(axes) as Axis[]).filter(axis => paper.facets[axis]?.length).map(axis =>
      <div key={axis} style={{display:"contents"}}><dt>{axes[axis]}</dt><dd>{paper.facets[axis]?.map(value =>
        <Link key={value} onClick={() => taxonomySelected(axis, value, "paper_tag")} to={"/catalog?" + new URLSearchParams({[axis]:value})}>{terms.data?.[axis]?.[value] || value}</Link>)}</dd></div>
    )}
    {post && <>
      <dt>Post type</dt>
      <dd><Link to={"/catalog?" + new URLSearchParams({ kind: "post", post_type: post.post_type })}>{postTypeLabel(post.post_type)}</Link></dd>
      {post.subtopics.length > 0 && <><dt>Subtopics</dt><dd>{post.subtopics.map(subtopicLabel).join(", ")}</dd></>}
      {post.authors.length > 0 && <><dt>Authors</dt><dd>{post.authors.join(", ")}</dd></>}
      <dt>Scores</dt>
      <dd className="discovery-post-scores">
        <span>Technical depth {post.technical_depth}/4</span>
        <span>Originality {post.originality}/4</span>
        <span>Agent relevance {post.agent_relevance}/4</span>
      </dd>
      {flags.length > 0 && <><dt>Flags</dt><dd>{flags.join(" · ")}</dd></>}
      {post.caveat && <><dt>Caveat</dt><dd>{post.caveat}</dd></>}
    </>}
    </dl>
    <div className="discovery-resources">
      {paper.artifact_url && <a onClick={() => resourceClicked(paper.paper_id, externalResource(paper.artifact_url!, "artifact"))} href={paper.artifact_url} target="_blank" rel="noreferrer">Open project artifact ↗</a>}
      {paper.has_text
        ? <a onClick={() => resourceClicked(paper.paper_id, "cached_text")} href={apiUrl("/api/v1/catalog/papers/" + encodeURIComponent(paper.paper_id) + "/text")}>Read cached text</a>
        : <span>{kind === "paper" && "No cached text. "}<a onClick={() => resourceClicked(paper.paper_id, externalResource(paper.source_url, "source"))} href={paper.source_url} target="_blank" rel="noreferrer">{kind === "post" ? "Read original post" : kind === "repository" ? "View original repository" : "Read at source"} ↗</a></span>}
    </div>
  </section>;
}
