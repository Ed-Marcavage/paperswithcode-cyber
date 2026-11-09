import { CatalogFacetSelect } from "@/components/CatalogFacetSelect";
import { paperLinkHandlers, taxonomySelected } from "@/lib/catalogAnalytics";
import { useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { axes, type Axis, browseQuery, filtersQuery } from "@/lib/api/discovery";
import "./DiscoveryCatalog.css";

const PAGE = 25;
export default function DiscoveryCatalogView() {
  const [params, setParams] = useSearchParams();
  const terms = useQuery(filtersQuery);
  const requested = Number(params.get("offset"));
  const offset = Number.isSafeInteger(requested) && requested >= 0 ? requested : 0;
  const query = new URLSearchParams();
  for (const axis of Object.keys(axes)) {
    const value = params.get(axis);
    if (value) query.set(axis, value);
  }
  const hasFilters = query.size > 0;
  if (hasFilters) query.set("include_facet_counts", "true");
  query.set("offset", String(offset));
  query.set("limit", String(PAGE));
  const papers = useQuery(browseQuery(query));
  function change(key: string, value: string) {
    const next = new URLSearchParams(params);
    if (key !== "offset") next.delete("offset");
    if (!value || (key === "offset" && value === "0")) next.delete(key);
    else next.set(key, value);
    setParams(next);
  }
  function pageHref(at: number) {
    const next = new URLSearchParams(params);
    if (at) next.set("offset", String(at));
    else next.delete("offset");
    return "/catalog" + (next.size ? "?" + next.toString() : "");
  }
  return <main className="page discovery">
    <header className="feed-header"><div>
      <h1 className="feed-title">Browse <em>catalog</em></h1>
      <p className="feed-subtitle">Filter cybersecurity research by what it studies and what it contributes.</p>
    </div></header>
    <div className="discovery-filters">
      {(Object.keys(axes) as Axis[]).map(axis => <CatalogFacetSelect key={axis} axis={axis}
        selected={params.get(axis) || ""} options={terms.data?.[axis]} counts={papers.data?.facet_counts?.[axis]}
        disabled={terms.isPending || (hasFilters && papers.isPending)}
        onChange={value => { taxonomySelected(axis, value, "catalog_filter"); change(axis, value); }} />)}
      {hasFilters && <button type="button" onClick={() => setParams({})}>Clear filters</button>}
    </div>
    {terms.isError || papers.isError ? <p role="alert">Could not load the catalog. <button onClick={() => { void papers.refetch(); void terms.refetch(); }}>Try again</button></p>
      : papers.isPending ? <p role="status">Loading papers…</p>
      : <><p role="status" className="discovery-count">{papers.data.total} {papers.data.total === 1 ? "paper" : "papers"}{papers.data.results.length > 0 && ` · Showing ${offset + 1}–${offset + papers.data.results.length}`}</p>
        <ul className="discovery-list">{papers.data.results.map(p => <li key={p.paper_id}>
          <Link to={"/paper/" + encodeURIComponent(p.reference)} {...paperLinkHandlers(p.paper_id, p.title, "title", "catalog", p.facets)}>{p.title}</Link>
          <small>{[...(p.facets.year || []), ...(p.facets.contribution || []).map(slug => terms.data?.contribution?.[slug] || slug)].join(" · ")}</small>
        </li>)}</ul>
        {papers.data.results.length === 0 && <p>No papers match this selection.</p>}
        <nav className="discovery-pager" aria-label="Catalog pages">
          {offset > 0 && <Link rel="prev" to={pageHref(Math.max(0, offset - PAGE))}>Previous</Link>}
          {offset + PAGE < papers.data.total && <Link rel="next" to={pageHref(offset + PAGE)}>Next</Link>}
        </nav>
      </>}
  </main>;
}
