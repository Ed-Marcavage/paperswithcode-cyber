import { isDiscoveryCatalog } from "@/lib/apiUrl";
import React, { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { Alert, AlertDescription } from "@/components/ui/alert";
import type { Organization } from "@/lib/api/catalog.types";
import { catalogApi } from "@/lib/api/catalog";
import "./Organizations.css";
import { catalogQueryKeys, TEN_MINUTES } from "@/lib/api/queryKeys";

type SortMode = "trending" | "papers" | "stars" | "name";

const parseSort = (value: string | null): SortMode =>
  value === "papers" || value === "stars" || value === "name" ? value : "trending";

const Logo: React.FC<{ organization: Organization }> = ({ organization }) => {
  const [failed, setFailed] = useState(false);
  if (!organization.logo_url || failed) {
    return (
      <span className="organization-logo organization-logo--fallback" aria-hidden="true">
        {organization.name.slice(0, 1).toUpperCase()}
      </span>
    );
  }
  return (
    <span className="organization-logo">
      <img
        src={organization.logo_url}
        alt=""
        width={48}
        height={48}
        onError={() => setFailed(true)}
      />
    </span>
  );
};

const OrganizationsIndexView: React.FC = () => {
  const discovery = isDiscoveryCatalog();
  const [params, setParams] = useSearchParams();
  const sort = parseSort(params.get("sort"));
  const query = params.get("q") ?? "";
  const organizationsQ = useQuery({
    queryKey: [...catalogQueryKeys.organizations, "featured", discovery ? sort : undefined],
    queryFn: () => catalogApi.organizationIndex(discovery ? sort : undefined),
    staleTime: TEN_MINUTES,
  });

  const setView = (next: { sort?: SortMode; query?: string }) => {
    const updated = new URLSearchParams(params);
    const nextSort = next.sort ?? sort;
    const nextQuery = next.query ?? query;
    if (nextSort === "trending") updated.delete("sort");
    else updated.set("sort", nextSort);
    if (nextQuery.trim()) updated.set("q", nextQuery);
    else updated.delete("q");
    setParams(updated);
  };

  const organizations = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase();
    const filtered = (organizationsQ.data?.results ?? []).filter((organization) =>
      [organization.name, organization.slug, organization.hf_slug ?? ""]
        .join(" ")
        .toLocaleLowerCase()
        .includes(needle),
    );
    if (discovery) return filtered;
    if (sort === "papers") {
      return [...filtered].sort(
        (a, b) =>
          (b.paper_count ?? 0) - (a.paper_count ?? 0) ||
          a.name.localeCompare(b.name) ||
          a.slug.localeCompare(b.slug),
      );
    }
    if (sort === "name") {
      return [...filtered].sort(
        (a, b) => a.name.localeCompare(b.name) || a.slug.localeCompare(b.slug),
      );
    }
    return filtered;
  }, [organizationsQ.data, query, sort, discovery]);

  return (
    <div className="page organizations-page">
      <div className="feed-header">
        <div>
          <h1 className="feed-title">
            {!discovery && "AI "}<em>Organizations</em>
          </h1>
          <div className="feed-subtitle">
            {discovery ? "Browse security research, engineering posts, and repositories by organization." : "Explore papers from leading AI organizations, ranked by sustained community momentum over the past 30 days."}
          </div>
        </div>
      </div>

      <section aria-labelledby="organizations-heading">
        <div className="organizations-section-heading">
          <h2 id="organizations-heading">
            {organizationsQ.data
              ? `${organizationsQ.data.count.toLocaleString()} organizations`
              : "Organizations"}
          </h2>
          <span>
            {sort === "trending"
              ? "Ranked by 30-day momentum"
              : sort === "papers"
                ? "Sorted by linked papers"
                : sort === "stars" ? "Stars across cataloged repositories" : "Sorted A–Z"}
          </span>
        </div>
        <div className="organizations-controls">
          <label>
            <span className="sr-only">Search organizations</span>
            <input
              type="search"
              value={query}
              onChange={(event) => setView({ query: event.target.value })}
              placeholder="Search organizations"
            />
          </label>
          <div className="organizations-sort" aria-label="Sort organizations">
            {(
              [
                ["trending", "Trending"],
                ["papers", "Most papers"],
                ...(discovery ? [["stars", "Most stars"]] as const : []),
                ["name", "A–Z"],
              ] as const
            ).map(([value, label]) => (
              <button
                type="button"
                key={value}
                className={sort === value ? "active" : ""}
                aria-pressed={sort === value}
                onClick={() => setView({ sort: value })}
              >
                {label}
              </button>
            ))}
          </div>
        </div>

        {organizationsQ.isLoading ? (
          <div
            className="organizations-grid"
            aria-busy="true"
            aria-label="Loading organizations"
          >
            {Array.from({ length: 12 }).map((_, index) => (
              <div key={index} className="organization-card organization-card-skeleton">
                <div className="organization-card-header">
                  <span className="organization-logo" />
                  <div>
                    <span className="organization-skeleton-line" />
                    <span className="organization-skeleton-line short" />
                  </div>
                </div>
                <div className="organization-card-metrics">
                  <span className="organization-skeleton-line short" />
                </div>
                <div className="organization-highlight">
                  <span className="organization-skeleton-line" />
                  <span className="organization-skeleton-line" />
                </div>
              </div>
            ))}
          </div>
        ) : organizationsQ.error ? (
          <Alert variant="destructive">
            <AlertDescription>
              Failed to load organizations.{" "}
              <button type="button" onClick={() => organizationsQ.refetch()}>
                Try again
              </button>
            </AlertDescription>
          </Alert>
        ) : organizations.length === 0 ? (
          <div className="organizations-empty">No organizations match “<span className="ph-mask">{query}</span>”.</div>
        ) : (
          <div className="organizations-grid">
            {organizations.map((organization) => {
              const count = organization.paper_count ?? 0;
              const showStars = discovery && sort === "stars";
              const workCounts = [
                [count, "paper", "papers"],
                [organization.post_count ?? 0, "post", "posts"],
                [organization.repository_count ?? 0, "repository", "repositories"],
              ] as const;
              const [primaryCount, singular, plural] = discovery && count === 0
                ? workCounts.reduce((largest, work) => work[0] > largest[0] ? work : largest)
                : workCounts[0];
              const kinds = workCounts
                .filter(([n, kind]) => (n > 0 || kind === "paper") &&
                  (showStars || singular === "paper" || kind !== singular))
                .map(([n, singular, plural]) => `${n} ${n === 1 ? singular : plural}`).join(" · ");
              const githubLogin = organization.github_url?.split("/").filter(Boolean).pop();
              const years =
                organization.first_paper_year && organization.latest_paper_year
                  ? organization.first_paper_year === organization.latest_paper_year
                    ? String(organization.first_paper_year)
                    : `${organization.first_paper_year}–${organization.latest_paper_year}`
                  : null;
              return (
                <Link
                  key={organization.id}
                  to={`/orgs/${organization.slug}`}
                  className="organization-card"
                  aria-label={discovery ? `Browse ${organization.name}` : count ? `Browse ${count.toLocaleString()} ${organization.name} papers` : `Browse ${organization.name} papers`}
                >
                  <div className="organization-card-header">
                    <Logo organization={organization} />
                    <div>
                      <h3>{organization.name}</h3>
                      {discovery ? (githubLogin && <span>@{githubLogin}</span>) : <span>@{organization.hf_slug ?? organization.slug}</span>}
                    </div>
                  </div>
                  <div className="organization-card-metrics">
                    <strong>{showStars ? (organization.catalog_stars?.toLocaleString() ?? "—") : primaryCount.toLocaleString()}</strong>
                    <span>{showStars ? "stars" : primaryCount === 1 ? singular : plural}</span>
                    {discovery && <span className="organization-kind-summary">{kinds}
                      {!showStars && organization.catalog_stars != null && ` · ★ ${organization.catalog_stars.toLocaleString()}`}
                    </span>}
                    {sort === "trending" && (!discovery || (organization.organization_trending_score ?? 0) > 0) && organization.trending_rank && (
                      <span className="organization-rank">
                        #{organization.trending_rank}
                      </span>
                    )}
                  </div>
                  <div className="organization-highlight">
                    <span>{discovery ? "Featured work" : "Trending paper"}</span>
                    <strong>
                      {organization.top_trending_paper?.title ?? "No papers indexed yet"}
                    </strong>
                  </div>
                  <div className="organization-card-footer">
                    {years ? `${discovery ? "Catalog" : "Publishing"} ${years}` : discovery ? "View profile" : "Research archive ready"}
                    <span aria-hidden="true">↗</span>
                  </div>
                </Link>
              );
            })}
          </div>
        )}
      </section>
    </div>
  );
};

export default OrganizationsIndexView;
