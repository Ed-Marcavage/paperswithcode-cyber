import { useEffect, useRef, useState } from "react";
import { externalResource, paperOpened, resourceClicked, taxonomySelected } from "@/lib/catalogAnalytics";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { axes, type Axis, discoveryPaperQuery, filtersQuery } from "@/lib/api/discovery";
import { apiUrl } from "@/lib/apiUrl";
import { parseGitHubRepoUrl } from "@/lib/github";
import { postTypeLabel, repositoryReferencesHref, subtopicLabel } from "@/lib/industryPost";
import "@/views/DiscoveryCatalog.css";

/**
 * Catalog details of a paper, post or repository. A post with a preview image (its page
 * screenshot, `thumbnailUrl`) shows it as a second column beside the rows, linking to the
 * original post, with "Read original post" under it; without one the rows take the width.
 */
export function DiscoveryPaper({ paperId, thumbnailUrl = null, title = "" }: { paperId: string; thumbnailUrl?: string | null; title?: string }) {
  const { data: paper, isError } = useQuery(discoveryPaperQuery(paperId));
  const terms = useQuery(filtersQuery);
  // Remember which image failed, so a different post or a refreshed image is shown again.
  const [failedPreview, setFailedPreview] = useState<string | null>(null);
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
  const repository = kind === "repository" ? parseGitHubRepoUrl(paper.source_url.replace(/\/$/, "")) : null;
  const flags = post ? [
    post.reports_benchmark_results && "Reports benchmark results",
    post.agent_harness_engineering && "Agent harness engineering",
  ].filter(Boolean) : [];
  const sourceLink = <a onClick={() => resourceClicked(paper.paper_id, externalResource(paper.source_url, "source"))} href={paper.source_url} target="_blank" rel="noreferrer">{kind === "post" ? "Read original post" : kind === "repository" ? "View original repository" : "Read at source"} ↗</a>;
  const preview = post && thumbnailUrl && thumbnailUrl !== failedPreview ? thumbnailUrl : null;
  const label = post?.curated_title || title || paper.title;
  return <section className={`discovery-paper${preview ? " has-preview" : ""}`} aria-label="Catalog details">
    <h2>Catalog details</h2>
    {post && <p className="tldr-box discovery-post-tldr">{post.tldr}</p>}
    <div className="discovery-paper-body">
      <div className="discovery-paper-rows">
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
          {repository && <Link to={repositoryReferencesHref(repository.owner, repository.repository)}>Papers and posts referencing this repository →</Link>}
          {paper.artifact_url && <a onClick={() => resourceClicked(paper.paper_id, externalResource(paper.artifact_url!, "artifact"))} href={paper.artifact_url} target="_blank" rel="noreferrer">Open project artifact ↗</a>}
          {paper.has_text
            ? <a onClick={() => resourceClicked(paper.paper_id, "cached_text")} href={apiUrl("/api/v1/catalog/papers/" + encodeURIComponent(paper.paper_id) + "/text")}>Read cached text</a>
            : !preview && <span>{kind === "paper" && "No cached text. "}{sourceLink}</span>}
        </div>
      </div>
      {preview && <aside className="discovery-paper-preview" aria-label="Original post">
        <a className="discovery-paper-shot" href={paper.source_url} target="_blank" rel="noopener noreferrer"
          aria-label={`Open the original post: ${label}`}
          onClick={() => resourceClicked(paper.paper_id, externalResource(paper.source_url, "source"))}>
          <img src={preview} alt="" width={400} height={550} loading="lazy" decoding="async" onError={() => setFailedPreview(preview)} />
        </a>
        {sourceLink}
      </aside>}
    </div>
  </section>;
}
