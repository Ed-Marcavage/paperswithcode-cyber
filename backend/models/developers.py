from pydantic import BaseModel, Field


class Developer(BaseModel):
    github_id: int
    login: str
    repository_count: int
    agent_work_count: int = Field(
        0, description="Distinct research papers and agent-related posts (review agent relevance at least "
        "Trending's MIN_AGENT_RELEVANCE) that credit one of the matching repositories: a post's original "
        "repository or a paper's official implementation",
    )
    featured_repo: str
    owned_stars: int | None = None


class Developers(BaseModel):
    count: int
    results: list[Developer]
    facet_counts: dict[str, dict[str, int]] | None = None


class DeveloperRepository(BaseModel):
    github_repo_id: int
    full_name: str
    owns: bool
    commits: int


class DeveloperProfile(BaseModel):
    github_id: int
    login: str
    repositories: list[DeveloperRepository]
