import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { format, parseISO } from "date-fns";
import { Link } from "react-router-dom";

import { industryHighlightsQuery, type DiscoveryWork } from "@/lib/api/discovery";
import { assetUrl } from "@/lib/apiUrl";
import { paperLinkHandlers } from "@/lib/catalogAnalytics";
import {
  ALL_INDUSTRY_POSTS_HREF, authorsLabel, postTypeLabel, publisherHost, TRENDING_INDUSTRY_SURFACE,
} from "@/lib/industryPost";

function shortDate(iso: string | null | undefined): string | null {
  if (!iso) return null;
  try {
    return format(parseISO(iso), "MMM d, yyyy");
  } catch {
    return null;
  }
}

/** The post's preview image; nothing at all (no empty box) when it has none or it fails to load.
 * Decorative: the title link, stretched over the card, is what opens the post. */
function PickPreview({ src }: { src: string | null }) {
  const [failed, setFailed] = useState(false);
  if (!src || failed) return null;
  return (
    <div className="industry-card-thumb">
      <img src={src} alt="" loading="lazy" decoding="async" onError={() => setFailed(true)} />
    </div>
  );
}

/** A pick is any catalog work. A reviewed post shows its publisher, post type and summary; a paper
 * shows its authors and abstract; a post without a review shows its publisher and stored summary. */
function IndustryPostCard({ work }: { work: DiscoveryWork }) {
  const post = work.post;
  const isPost = (work.kind ?? work.facets.kind?.[0] ?? "post") === "post";
  const source = isPost
    ? work.publisher || post?.curated_company || publisherHost(work.source_url)
    : authorsLabel(work.authors);
  const type = post ? postTypeLabel(post.post_type) : isPost ? "Post" : "Paper";
  const title = post?.curated_title || work.title;
  const summary = post?.tldr || work.summary;
  const meta = [source, type, shortDate(work.date_published)].filter(Boolean);
  const href = "/paper/" + encodeURIComponent(work.reference);
  return (
    <article className="industry-card">
      <PickPreview src={assetUrl(work.thumbnail_url)} />
      <div className="industry-card-body">
        <div className="industry-card-meta">{meta.join(" · ")}</div>
        <h3 className="industry-card-title">
          <Link to={href}
            {...paperLinkHandlers(work.paper_id, work.title, "title", TRENDING_INDUSTRY_SURFACE, work.facets)}>
            {title}
          </Link>
        </h3>
        {summary && <p className="industry-card-tldr">{summary}</p>}
      </div>
    </article>
  );
}

/**
 * Editor's picks above the Trending feed: one row of the editor's three most important posts and
 * papers (the first pins, in pin order). The feeds below leave them out. Renders nothing until loaded.
 */
export function TrendingIndustry() {
  const highlights = useQuery(industryHighlightsQuery);
  if (!highlights.data || highlights.data.results.length === 0) return null;
  return (
    <section className="trending-industry" aria-labelledby="trending-industry-heading">
      <div className="trending-industry-header">
        <h2 id="trending-industry-heading" className="trending-industry-heading">{highlights.data.heading || "Editor's picks"}</h2>
        <Link to={ALL_INDUSTRY_POSTS_HREF} className="trending-industry-more">All industry posts →</Link>
      </div>
      <div className="trending-industry-grid">
        {highlights.data.results.map(work => <IndustryPostCard key={work.paper_id} work={work} />)}
      </div>
    </section>
  );
}
