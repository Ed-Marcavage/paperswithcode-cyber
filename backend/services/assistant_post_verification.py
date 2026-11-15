"""Subject floor for follow-up counts over find_posts' any-word relation."""

from sqlalchemy import text

MIN_SUBJECT_LEXEMES = 2
MAX_SUBJECT_DOCUMENT_FRACTION = 0.10
SUBJECT_RULE = 'least_frequent_and_two_subject_lexemes_v1'


def subject_count_statement(sql, params, vector, all_words):
    # Frequencies use exactly the structured-filter population, before text
    # matching. Include zero-frequency terms: a publisher's unrelated posts
    # cannot rescue a subject absent from that publisher. PostgreSQL supplies
    # the same English stemming as find_posts; only title + tldr are evidence.
    params.update(min_subject_lexemes=MIN_SUBJECT_LEXEMES,
                  max_subject_document_fraction=MAX_SUBJECT_DOCUMENT_FRACTION)
    sql += f""",
    query_terms AS (
        SELECT term FROM unnest(tsvector_to_array(to_tsvector('english', :query))) AS words(term)
    ), corpus_documents AS MATERIALIZED (
        SELECT id, tsvector_to_array({vector}) AS lexemes,
               tsvector_to_array(to_tsvector('english', coalesce(publisher, ''))) AS publisher_lexemes
          FROM scored
    ), documents AS MATERIALIZED (
        SELECT corpus_documents.* FROM corpus_documents JOIN filtered USING (id)
    ), frequencies AS (
        SELECT term,
               (SELECT count(*) FROM documents WHERE term = ANY(lexemes)) AS document_count,
               (SELECT count(*) FROM corpus_documents WHERE term = ANY(lexemes)) AS corpus_count
          FROM query_terms
    ), subject AS (
        SELECT coalesce(array_agg(term ORDER BY term), ARRAY[]::text[]) AS lexemes,
               coalesce(min(document_count), 0) AS frequency
          FROM frequencies WHERE document_count = (SELECT min(document_count) FROM frequencies)
    ), distinctive AS (
        SELECT term FROM frequencies WHERE corpus_count <=
            (SELECT count(*) FROM corpus_documents) * :max_subject_document_fraction
    ), verified AS (
        SELECT matched.* FROM matched JOIN documents USING (id) CROSS JOIN subject
        WHERE {vector} @@ {all_words}
           OR (documents.lexemes && subject.lexemes AND
               (SELECT count(*) FROM distinctive WHERE term = ANY(documents.lexemes)
                    AND NOT term = ANY(documents.publisher_lexemes)) >= :min_subject_lexemes)
    ) SELECT count(DISTINCT id) AS match_count,
             count(DISTINCT id) FILTER (WHERE NOT (
                 id::text = ANY(CAST(:seen_ids AS text[]))
                 OR coalesce(arxiv_id, '') = ANY(CAST(:seen_arxiv AS text[])))) AS new_match_count,
             (SELECT count(*) FROM matched) AS raw_match_count,
             (SELECT count(*) FROM documents) AS eligible_post_count,
             (SELECT count(*) FROM corpus_documents) AS corpus_post_count,
             (SELECT coalesce(array_agg(term ORDER BY term), ARRAY[]::text[]) FROM query_terms) AS query_lexemes,
             (SELECT coalesce(array_agg(term ORDER BY term), ARRAY[]::text[]) FROM distinctive) AS distinctive_lexemes,
             (SELECT lexemes FROM subject) AS subject_lexemes,
             (SELECT frequency FROM subject) AS subject_frequency
        FROM verified
"""
    return text(sql), params
