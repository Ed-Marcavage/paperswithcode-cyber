import { useQuery } from "@tanstack/react-query";
import { format, parseISO } from "date-fns";
import { Link } from "react-router-dom";

import { EditorsPickChip, FeaturedChip } from "@/components/Chips";
import { industryHighlightsQuery, type DiscoveryWork } from "@/lib/api/discovery";
import { paperLinkHandlers } from "@/lib/catalogAnalytics";
import {
  ALL_INDUSTRY_POSTS_HREF, industryHeading, postTypeLabel, publisherHost, TRENDING_INDUSTRY_SURFACE,
} from "@/lib/industryPost";

function shortDate(iso: string | null | undefined): string | null {
  if (!iso) return null;
  try {
    return format(parseISO(iso), "MMM d, yyyy");
  } catch {
    return null;
  }
}

function IndustryPostCard({ work }: { work: DiscoveryWork }) {
  const post = work.post;
  const company = post?.curated_company || publisherHost(work.source_url);
  const title = post?.curated_title || work.title;
  const meta = [company, post && postTypeLabel(post.post_type), shortDate(work.date_published)].filter(Boolean);
  return (
    <article className="industry-card">
      <div className="industry-card-meta">{meta.join(" · ")}</div>
      <h3 className="industry-card-title">
        <Link to={"/paper/" + encodeURIComponent(work.reference)}
          {...paperLinkHandlers(work.paper_id, work.title, "title", TRENDING_INDUSTRY_SURFACE, work.facets)}>
          {title}
        </Link>
      </h3>
      {post?.tldr && <p className="industry-card-tldr">{post.tldr}</p>}
      {(post?.tier === "featured" || post?.curated) && (
        <div className="industry-card-chips">
          {post?.tier === "featured" && <FeaturedChip />}
          {post?.curated && <EditorsPickChip />}
        </div>
      )}
    </article>
  );
}

/** Recent industry engineering posts shown above the Trending feed. Renders nothing until loaded. */
export function TrendingIndustry() {
  const highlights = useQuery(industryHighlightsQuery);
  if (!highlights.data || highlights.data.results.length === 0) return null;
  return (
    <section className="trending-industry" aria-labelledby="trending-industry-heading">
      <h2 id="trending-industry-heading" className="trending-industry-heading">{industryHeading(highlights.data)}</h2>
      <div className="trending-industry-grid">
        {highlights.data.results.map(work => <IndustryPostCard key={work.paper_id} work={work} />)}
      </div>
      <Link to={ALL_INDUSTRY_POSTS_HREF} className="trending-industry-more">See all industry posts →</Link>
    </section>
  );
}
