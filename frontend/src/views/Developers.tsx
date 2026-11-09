import { useState } from "react";
import { Link, useLocation, useParams, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import NotFound from "@/pages/NotFound";
import { CatalogFacetSelect } from "@/components/CatalogFacetSelect";
import { filtersQuery } from "@/lib/api/discovery";
import { useDocumentTitle } from "@/hooks/useDocumentTitle";
import "./DiscoveryCatalog.css";
import { developerAxes, developerParams, developerPageSize, getDeveloper, getDevelopers } from "@/lib/api/developers";
import { TEN_MINUTES } from "@/lib/api/queryKeys";
import "./Organizations.css";
import "./Developers.css";

function Avatar({ id, login }: { id: number; login: string }) {
  const [failed, setFailed] = useState(false);
  return (
    <span className="organization-logo developer-avatar" aria-hidden="true">
      {failed ? login[0].toUpperCase() : (
        <img src={`https://avatars.githubusercontent.com/u/${id}?s=96`} loading="lazy" alt=""
          onError={() => setFailed(true)} />
      )}
    </span>
  );
}

function Feedback({ loading, retry }: { loading: boolean; retry: () => void }) {
  return <div className="organizations-empty" role="status">{loading ? "Loading developers…" : (
    <>Couldn’t load developers. <button type="button" onClick={retry}>Try again</button></>
  )}</div>;
}

export function DevelopersIndex() {
  useDocumentTitle("Developers");
  const [params, setParams] = useSearchParams();
  const q = params.get("q") ?? "";
  const page = Math.max(1, Math.min(100000, Number.parseInt(params.get("page") ?? "", 10) || 1));
  const terms = useQuery(filtersQuery);
  const request = developerParams(params, page);
  const sortByStars = params.get("sort") === "stars";
  const repository = params.get("repository");
  const filtered = developerAxes.some(axis => params.get(axis)) || !!repository;
  const query = useQuery({
    queryKey: ["developers", request], queryFn: () => getDevelopers(request), staleTime: TEN_MINUTES,
  });
  function change(key: string, value: string, replace = false) {
    const next = new URLSearchParams(params);
    if (key !== "page") next.delete("page");
    if (value && !(key === "page" && value === "1")) next.set(key, value);
    else next.delete(key);
    setParams(next, { replace });
  }
  const count = query.data?.count ?? 0;
  const pages = Math.max(1, Math.ceil(count / developerPageSize));
  return (
    <div className="page organizations-page developers-page">
      <header className="feed-header"><div>
        <h1 className="feed-title"><em>Developers</em></h1>
        <div className="feed-subtitle">GitHub accounts that own or contribute to repositories in the catalog.</div>
      </div></header>
      <section aria-labelledby="developers-heading">
        <div className="organizations-section-heading">
          <h2 id="developers-heading">{query.data ? `${count.toLocaleString()} ${count === 1 ? "developer" : "developers"}` : "Developers"}</h2>
          <span>{sortByStars ? "Stars on matching owned repos" : "Most tracked repos"}</span>
        </div>
        <div className="organizations-controls">
          <label><span className="sr-only">Search GitHub usernames</span>
            <input type="search" maxLength={100} value={q} placeholder="Search GitHub usernames"
              onChange={event => change("q", event.target.value, true)} />
          </label>
          <div className="organizations-sort" aria-label="Sort developers">
            <button type="button" aria-pressed={!sortByStars} className={!sortByStars ? "active" : ""} onClick={() => change("sort", "")}>Most tracked repos</button>
            <button type="button" aria-pressed={sortByStars} className={sortByStars ? "active" : ""} onClick={() => change("sort", "stars")}>Most stars</button>
          </div>
        </div>
        <div className="discovery-filters developer-filters">
          {developerAxes.map(axis => <CatalogFacetSelect key={axis} axis={axis} selected={params.get(axis) || ""}
            options={terms.data?.[axis]} counts={query.data?.facet_counts?.[axis]} disabled={!terms.data || !query.data}
            onChange={value => change(axis, value)} />)}
          {repository && <button type="button" onClick={() => change("repository", "")}>Remove {repository} ×</button>}
          {(filtered || q) && <button type="button" onClick={() => setParams(sortByStars ? {sort: "stars"} : {})}>Clear filters</button>}
        </div>
        {terms.isError && <p role="alert">Couldn’t load filter options. <button onClick={() => terms.refetch()}>Try again</button></p>}

        {!query.data ? <Feedback loading={query.isLoading} retry={() => query.refetch()} />
          : query.data.results.length === 0 ? (
            <div className="organizations-empty">{count ? "No developers on this page." :
              filtered ? "No developers match these filters." : q ? `No developers match “${q}”.` : "No tracked developers yet."}</div>
          ) : (
            <div className="organizations-grid">
              {query.data.results.map(dev => (
                <Link key={dev.github_id} className="organization-card developer-card" state={{ directorySearch: params.toString() }} to={`/developers/${dev.github_id}`}>
                  <div className="organization-card-header"><Avatar id={dev.github_id} login={dev.login} />
                    <div><h3>{dev.login}</h3></div>
                  </div>
                  <div className="organization-card-metrics">
                    <strong>{sortByStars ? (dev.owned_stars?.toLocaleString() ?? "—") : dev.repository_count}</strong>
                    <span>{sortByStars ? "owned repo stars" : filtered ? "matching repos" : dev.repository_count === 1 ? "tracked repo" : "tracked repos"}</span>
                  </div>
                  <div className="organization-highlight"><span>{filtered ? "Matching work" : "Featured work"}</span><strong>{dev.featured_repo}</strong></div>
                </Link>
              ))}
            </div>
          )}
        {query.data && (pages > 1 || page > 1) && <nav className="developer-pagination" aria-label="Developer directory pages">
          <button disabled={page === 1} onClick={() => change("page", String(Math.min(page - 1, pages)))}>Previous</button>
          <span>Page {page} of {pages}</span>
          <button disabled={page >= pages} onClick={() => change("page", String(page + 1))}>Next</button>
        </nav>}
      </section>
    </div>
  );
}

export function DeveloperDetail() {
  const { id = "" } = useParams();
  const directorySearch = useLocation().state?.directorySearch;
  const valid = /^\d{1,18}$/.test(id);
  const query = useQuery({
    queryKey: ["developer", id], queryFn: () => getDeveloper(id), enabled: valid, staleTime: TEN_MINUTES,
  });
  if (!valid || query.data === null) return <NotFound />;
  if (!query.data) return <div className="page"><Feedback loading={query.isLoading} retry={() => query.refetch()} /></div>;
  const dev = query.data;
  return (
    <div className="page organizations-page developers-page">
      <Link className="developer-back" to={{pathname: "/developers", search: typeof directorySearch === "string" ? directorySearch : ""}}>← Developers</Link>
      <header className="feed-header developer-profile-header">
        <Avatar id={dev.github_id} login={dev.login} />
        <div><h1 className="feed-title">{dev.login}</h1>
          <a className="developer-github" href={`https://github.com/${dev.login}`}>GitHub profile ↗</a></div>
      </header>
      <section aria-labelledby="developer-work">
        <div className="organizations-section-heading">
          <h2 id="developer-work">Featured work</h2>
          <span>{dev.repositories.length} tracked {dev.repositories.length === 1 ? "repo" : "repos"}</span>
        </div>
        <div className="developer-work-list">
          {dev.repositories.map(repo => (
            <div key={repo.github_repo_id} className="developer-work-row">
              <span className="developer-work-main"><strong><a href={`https://github.com/${repo.full_name}`}>{repo.full_name} ↗</a></strong>
                <span>{[repo.owns && "Owns", repo.commits > 0 && "Contributed to"].filter(Boolean).join(" · ")}</span>
              </span>
              {repo.commits > 0 && <span className="developer-commits">{repo.commits.toLocaleString()} {repo.commits === 1 ? "commit" : "commits"}</span>}
              <Link className="developer-repo-team" to={`/developers?${new URLSearchParams({ repository: repo.full_name })}`}>View developers</Link>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
