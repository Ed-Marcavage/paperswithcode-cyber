import { useQuery } from "@tanstack/react-query";
import { format, parseISO } from "date-fns";
import { Link, useParams } from "react-router-dom";

import { useDocumentTitle } from "@/hooks/useDocumentTitle";
import { repositoryReferencesQuery, type RepositoryReference } from "@/lib/api/discovery";
import { isNotFound } from "@/lib/apiErrors";
import { formatStarCount } from "@/lib/frameworks";
import { knownStars, REFERENCE_ROLE_LABELS } from "@/lib/industryPost";
import NotFound from "@/pages/NotFound";
import "./Organizations.css";
import "./Developers.css";

function shortDate(iso: string | null): string | null {
  if (!iso) return null;
  try {
    return format(parseISO(iso), "MMM d, yyyy");
  } catch {
    return null;
  }
}

function ReferenceRow({ work }: { work: RepositoryReference }) {
  const meta = [
    work.kind === "post" ? "Industry post" : work.kind === "repository" ? "Repository entry" : "Paper",
    work.publisher,
    shortDate(work.date_published),
  ].filter(Boolean);
  return (
    <div className="developer-work-row">
      <span className="developer-work-main">
        <strong><Link to={`/paper/${encodeURIComponent(work.reference)}`}>{work.title}</Link></strong>
        <span>{meta.join(" · ")}</span>
        {work.evidence && <span className="repository-reference-evidence">{work.evidence}</span>}
      </span>
    </div>
  );
}

/** /repos/:owner/:name — the papers and industry posts that reference one GitHub repository, by role. */
export default function RepositoryReferencesView() {
  const { owner = "", name = "" } = useParams<{ owner: string; name: string }>();
  const query = useQuery(repositoryReferencesQuery(owner, name));
  useDocumentTitle(`${owner}/${name}`);
  if (isNotFound(query.error)) return <NotFound />;
  const data = query.data;
  const stars = data ? knownStars(data.repository) : null;
  return (
    <div className="page organizations-page developers-page">
      <nav className="breadcrumb" aria-label="Breadcrumb">
        <Link to="/catalog">Browse catalog</Link>
        <span> / </span>
        <span>Repositories</span>
      </nav>
      <header className="feed-header">
        <div>
          <div className="organizations-eyebrow">REPOSITORY</div>
          <h1 className="feed-title repository-references-title">{data ? `${data.repository.owner}/${data.repository.name}` : `${owner}/${name}`}</h1>
          {data && (
            <div className="feed-subtitle">
              {stars != null && <>★ {formatStarCount(stars)} stars · </>}
              <a className="developer-github" href={data.repository.url} target="_blank" rel="noreferrer">GitHub ↗</a>
              {" · "}
              <Link className="developer-github" to={`/developers?${new URLSearchParams({ repository: `${data.repository.owner}/${data.repository.name}` })}`}>View developers</Link>
            </div>
          )}
        </div>
      </header>
      {!data ? (
        <div className="organizations-empty" role="status">
          {query.isError
            ? <>Couldn’t load this repository. <button type="button" onClick={() => query.refetch()}>Try again</button></>
            : "Loading references…"}
        </div>
      ) : (
        <section aria-labelledby="repository-references">
          <div className="organizations-section-heading">
            <h2 id="repository-references">Referenced by</h2>
            <span>{data.total} {data.total === 1 ? "paper or post" : "papers and posts"}</span>
          </div>
          {data.total === 0 && <div className="organizations-empty">No catalog papers or posts reference this repository yet.</div>}
          {Object.entries(data.references).map(([role, works]) => (
            <section key={role} className="repository-reference-group" aria-label={REFERENCE_ROLE_LABELS[role] ?? role}>
              <h3 className="repository-reference-role">
                {REFERENCE_ROLE_LABELS[role] ?? role} <span>{works.length}</span>
              </h3>
              <div className="developer-work-list">
                {works.map((work) => <ReferenceRow key={work.paper_id} work={work} />)}
              </div>
            </section>
          ))}
        </section>
      )}
    </div>
  );
}
