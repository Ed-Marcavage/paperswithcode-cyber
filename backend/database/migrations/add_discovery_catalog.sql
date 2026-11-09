CREATE TABLE IF NOT EXISTS discovery_terms (
    axis text NOT NULL,
    value text NOT NULL,
    label text NOT NULL,
    PRIMARY KEY (axis, value)
);

CREATE TABLE IF NOT EXISTS discovery_works (
    paper_id bigint PRIMARY KEY REFERENCES papers(id) ON DELETE CASCADE,
    catalog_id text NOT NULL UNIQUE,
    facets jsonb NOT NULL,
    source_url text NOT NULL,
    artifact_url text,
    document_text text
);

CREATE TABLE IF NOT EXISTS discovery_previews (
    paper_id bigint PRIMARY KEY REFERENCES discovery_works(paper_id) ON DELETE CASCADE,
    digest text NOT NULL,
    jpeg bytea NOT NULL
);
