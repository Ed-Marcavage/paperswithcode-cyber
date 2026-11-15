import { CatalogFacetSelect } from "@/components/CatalogFacetSelect";
import { EditorsPickChip, FeaturedChip } from "@/components/Chips";
import { cyberCatalogDescription } from "@/lib/cyberCopy";
import { paperLinkHandlers, taxonomySelected } from "@/lib/catalogAnalytics";
import { useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import * as Dialog from "@radix-ui/react-dialog";
import { axes, type Axis, browseQuery, type DiscoveryWork, filtersQuery } from "@/lib/api/discovery";
import { POST_TYPE_LABELS, postTypeLabel, publisherHost } from "@/lib/industryPost";
import "./DiscoveryCatalog.css";

const PAGE = 25;
/** Industry-post controls, offered only while Source type is "post". */
const postControls = {
  tier: { label: "Tier", all: "All", options: { featured: "Featured", catalog: "Standard" } },
  post_type: { label: "Post type", all: "All", options: POST_TYPE_LABELS },
  order: { label: "Order", all: "Newest first", options: { featured: "Featured first" } },
} as const;
type PostControl = keyof typeof postControls;

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
  const showsPosts = params.get("kind") === "post";
  if (showsPosts) {
    for (const key of Object.keys(postControls)) {
      const value = params.get(key);
      if (value) query.set(key, value);
    }
  }
  const hasPostControls = showsPosts && Object.keys(postControls).some(key => params.get(key));
  query.set("offset", String(offset));
  query.set("limit", String(PAGE));
  const papers = useQuery(browseQuery(query));
  function change(key: string, value: string) {
    const next = new URLSearchParams(params);
    if (key !== "offset") next.delete("offset");
    if (!value || (key === "offset" && value === "0")) next.delete(key);
    else next.set(key, value);
    if (key === "kind" && value !== "post") for (const control of Object.keys(postControls)) next.delete(control);
    setParams(next);
  }
  function pageHref(at: number) {
    const next = new URLSearchParams(params);
    if (at) next.set("offset", String(at));
    else next.delete("offset");
    return "/catalog" + (next.size ? "?" + next.toString() : "");
  }
  const controls = <>
    {(Object.keys(axes) as Axis[]).map(axis => <CatalogFacetSelect key={axis} axis={axis}
      selected={params.get(axis) || ""} options={terms.data?.[axis]} counts={papers.data?.facet_counts?.[axis]}
      disabled={terms.isPending || (hasFilters && papers.isPending)}
      onChange={value => { taxonomySelected(axis, value, "catalog_filter"); change(axis, value); }} />)}
    {showsPosts && (Object.keys(postControls) as PostControl[]).map(key => {
      const control = postControls[key];
      return <label key={key}>{control.label}
        <select value={params.get(key) || ""} disabled={papers.isPending} onChange={e => change(key, e.target.value)}>
          <option value="">{control.all}</option>
          {Object.entries(control.options).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select>
      </label>;
    })}
  </>;
  const active = [
    ...(Object.keys(axes) as Axis[]).flatMap(axis => {
      const value = params.get(axis);
      return value ? [{ key: axis, label: axes[axis], value: terms.data?.[axis]?.[value] ?? value }] : [];
    }),
    ...(showsPosts ? (Object.keys(postControls) as PostControl[]).flatMap(key => {
      const value = params.get(key);
      const options: Record<string, string> = postControls[key].options;
      return value ? [{ key, label: postControls[key].label, value: options[value] ?? value }] : [];
    }) : []),
  ];
  return <main className="page discovery">
    <header className="feed-header"><div>
      <h1 className="feed-title">Browse <em>catalog</em></h1>
      <p className="feed-subtitle">{cyberCatalogDescription}</p>
    </div></header>
    {/* Phones: one Filters button opening a sheet, with active filters as removable chips. */}
    <div className="discovery-mobile-bar">
      <Dialog.Root>
        <Dialog.Trigger asChild>
          <button type="button" className="discovery-filters-button">
            <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"><path d="M2.5 4.5h11M4.5 8h7M6.5 11.5h3" /></svg>
            Filters{active.length > 0 && <span className="discovery-filters-badge" aria-label={`${active.length} active`}>{active.length}</span>}
          </button>
        </Dialog.Trigger>
        <Dialog.Portal>
          <Dialog.Overlay className="discovery-sheet-overlay" />
          <Dialog.Content className="discovery-sheet" aria-describedby={undefined}>
            <div className="discovery-sheet-head">
              <Dialog.Title className="discovery-sheet-title">Filters</Dialog.Title>
              <Dialog.Close className="discovery-sheet-close" aria-label="Close filters">
                <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"><path d="M4 4l8 8M12 4l-8 8" /></svg>
              </Dialog.Close>
            </div>
            <div className="discovery-sheet-body discovery-filters">{controls}</div>
            <div className="discovery-sheet-foot">
              <button type="button" className="discovery-sheet-clear" disabled={!active.length} onClick={() => setParams({})}>Clear all</button>
              <Dialog.Close className="discovery-sheet-apply">{papers.data ? `Show ${papers.data.total.toLocaleString("en-US")} ${papers.data.total === 1 ? "result" : "results"}` : "Show results"}</Dialog.Close>
            </div>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </div>
    {active.length > 0 && <ul className="discovery-chips" aria-label="Active filters">{active.map(item => <li key={item.key}>
      <button type="button" aria-label={`Remove filter ${item.label}: ${item.value}`} onClick={() => change(item.key, "")}>
        <span>{item.value}</span>
        <svg viewBox="0 0 16 16" width="12" height="12" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"><path d="M4.5 4.5l7 7M11.5 4.5l-7 7" /></svg>
      </button>
    </li>)}</ul>}
    {/* Wider screens: the inline row. */}
    <div className="discovery-filters discovery-filters-inline">
      {controls}
      <div className="discovery-filters-end">
        {(hasFilters || hasPostControls) && <button type="button" className="discovery-clear" onClick={() => setParams({})}>Clear filters</button>}
        </div>
    </div>
    {terms.isError || papers.isError ? <p role="alert">Could not load the catalog. <button onClick={() => { void papers.refetch(); void terms.refetch(); }}>Try again</button></p>
      : papers.isPending ? <p role="status" className="discovery-count">Loading the catalog…</p>
      : <><p role="status" className="discovery-count">{papers.data.total.toLocaleString("en-US")} {papers.data.total === 1 ? "result" : "results"}{papers.data.results.length > 0 && ` · Showing ${offset + 1}–${offset + papers.data.results.length}`}</p>
        <ul className="discovery-list">{papers.data.results.map(p => <li key={p.paper_id}>
          <Link to={"/paper/" + encodeURIComponent(p.reference)} {...paperLinkHandlers(p.paper_id, p.title, "title", "catalog", p.facets)}>{p.title}</Link>
          {p.facets.kind?.[0] === "post" ? <PostSummary work={p} details={[...(p.facets.year || []), ...(p.facets.contribution || []).map(slug => terms.data?.contribution?.[slug] || slug)]} />
            : <small>{[...(p.facets.year || []), ...(p.facets.contribution || []).map(slug => terms.data?.contribution?.[slug] || slug)].join(" · ")}</small>}
        </li>)}</ul>
        {papers.data.results.length === 0 && <p className="discovery-empty">Nothing in the catalog matches these filters.</p>}
        <nav className="discovery-pager" aria-label="Catalog pages">
          {offset > 0 && <Link rel="prev" to={pageHref(Math.max(0, offset - PAGE))}>Previous</Link>}
          {offset + PAGE < papers.data.total && <Link rel="next" to={pageHref(offset + PAGE)}>Next</Link>}
        </nav>
      </>}
  </main>;
}

/** List-row extras for an industry post: featured marker, post type, publisher and TL;DR. */
function PostSummary({ work, details }: { work: DiscoveryWork; details: string[] }) {
  const post = work.post;
  const meta = [post && postTypeLabel(post.post_type), work.publisher || publisherHost(work.source_url), ...details].filter(Boolean);
  return <>
    <span className="discovery-post-meta">
      {post?.tier === "featured" && <FeaturedChip />}
      {post?.curated && <EditorsPickChip />}
      <small>{meta.join(" · ")}</small>
    </span>
    {post?.tldr && <p className="discovery-tldr">{post.tldr}</p>}
  </>;
}
