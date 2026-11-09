from pydantic import BaseModel


class Developer(BaseModel):
    github_id: int
    login: str
    repository_count: int
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
