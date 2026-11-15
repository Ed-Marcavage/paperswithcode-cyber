"""Fake searches cover orchestration; PostgreSQL executes the lexical SQL live."""

import json
import time
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql

from backend.models.assistant_tools import FollowUpCandidate, FollowUpPostCheck
from backend.services import assistant_followups as followups
from backend.services.assistant_posts import search_statement
from backend.services.assistant_post_verification import SUBJECT_RULE
from backend.tests.assistant.test_find_posts import FakeSessions
from backend.tests.assistant.test_followups import state, suggest


class SearchCounts(FakeSessions):
    def __init__(self, counts):
        super().__init__()
        self.counts = iter(counts)

    def mappings(self):
        return SimpleNamespace(one=lambda: next(self.counts))

    @property
    def searches(self):
        return [(sql, params) for sql, params in self.calls if 'WITH posts AS' in sql]


def counts(total, new=None, **extra):
    return {'match_count': total, 'new_match_count': total if new is None else new, **extra}


@pytest.mark.parametrize('question,check,query', [
    ('How does Hadrian design sandboxing for agentic pentesting harnesses?', {'publisher': 'Hadrian'},
     'design sandboxing agentic pentesting harnesses'),
    ('How does Endor Labs engineer isolation in security harnesses for coding agents?', {'publisher': 'Endor Labs'},
     'engineer isolation security harnesses coding agents'),
    ('What has Microsoft published on AI-speed security evaluation and static analysis?', {'publisher': 'Microsoft'},
     'ai-speed security evaluation static analysis'),
    ('How does Snyk’s Evo remediation agent turn findings into pull requests?', {'publisher': 'Snyk'},
     'evo remediation agent turn findings pull requests'),
    ('Which posts compare sandbox isolation?', {'topic': 'ai-system-security'}, 'compare sandbox isolation'),
    ("How does Acme-Security's sandbox isolate credentials?", {'publisher': 'Acme-Security'}, 'sandbox isolate credentials'),
    ('Which defender posts cover ARTEX in intrusion campaigns and hunting?',
     {'query': 'ARTEX intrusion campaigns detection hunting'}, 'ARTEX intrusion campaigns detection hunting'),
])
def test_effective_query_uses_explicit_query_or_question_subject(question, check, query):
    candidate = FollowUpCandidate(question=question, check=check)
    effective, audit = followups.effective_check(candidate)
    assert effective.query == query and audit['effective_query'] == query
    assert 'min_agent_relevance' not in effective.model_fields_set
    assert audit['effective_filters'] == {**{k: v for k, v in check.items() if k != 'query'}, 'min_agent_relevance': 3}
    assert candidate.check.model_dump(exclude_unset=True) == check  # Original proposal stays intact.


def test_post_search_fallback_applies_filters_and_counts_only_qualified_new_matches():
    arguments = {'query': 'Evo remediation agent pull requests Snyk', 'topic': 'repair',
                 'subtopic': 'patch-verification', 'post_type': 'engineering-practice', 'publisher': 'Snyk',
                 'harness_engineering': False, 'published_after': '2026-01-01'}
    db = SearchCounts([counts(0), counts(1), counts(3, 2, raw_match_count=467, subject_lexemes=['evo'])])
    result = followups.read_counts(FollowUpPostCheck(**arguments), followups.SeenWorks(ids={'42'}), db, time.monotonic() + 3)
    assert result['match_count'] == 3 and result['new_match_count'] == 2
    assert result['raw_match_count'] == 467 and result['subject_rule'] == SUBJECT_RULE
    assert result['match_mode'] == 'any_word' and len(result['relaxations']) == 2
    assert result['effective_filters'] == {k: v for k, v in arguments.items() if k != 'query'}
    assert len(db.searches) == 3 and db.closed == 1
    for sql, params in db.searches:
        assert params['query'] == arguments['query'] and params['seen_ids'] == ['42']
        assert params['publisher'] == 'Snyk' and params['subtopic'] == 'patch-verification'
        assert params['post_type'] == 'engineering-practice' and params['harness_engineering'] is False
        assert json.loads(params['topic']) == {'topic': ['repair']}
        assert params['published_after'].isoformat() == '2026-01-01'
    assert '>= :min_agent_relevance' in db.searches[0][0]
    assert '>= :min_agent_relevance' not in db.searches[1][0] + db.searches[2][0]
    assert 'FROM verified' in db.searches[-1][0]


@pytest.mark.parametrize('minimum', [0, 3, 4])
def test_explicit_relevance_is_not_relaxed(minimum):
    db = SearchCounts([counts(1), counts(7)])
    check = FollowUpPostCheck(query='ARTEX campaigns', min_agent_relevance=minimum)
    result = followups.read_counts(check, followups.SeenWorks(), db, time.monotonic() + 3)
    assert result['match_mode'] == 'any_word' and not result['relevance_relaxed']
    assert result['effective_filters']['min_agent_relevance'] == minimum
    assert len(db.searches) == 2
    assert all('>= :min_agent_relevance' in sql and params['min_agent_relevance'] == minimum for sql, params in db.searches)


@pytest.mark.parametrize('sequence', [[counts(3)], [counts(0), counts(4)]])
def test_all_word_matches_count_without_subject_floor_and_stop_fallback(sequence):
    db = SearchCounts(sequence)
    result = followups.read_counts(FollowUpPostCheck(query='ARTEX'), followups.SeenWorks(), db, time.monotonic() + 3)
    assert result['match_mode'] == 'all_words' and result['subject_rule'] == 'all_words'
    assert result['match_count'] >= 3
    assert all('FROM verified' not in sql for sql, _ in db.searches)


def test_subject_sql_uses_same_english_lexemes_and_counts_full_relation_safely():
    query = "Evo' | !agent:* ; DROP TABLE papers; --"
    statement, params = search_statement({'query': query, 'publisher': "O'Reilly"}, seen=followups.SeenWorks(), any_word=True)
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert query not in sql and "O'Reilly" not in sql
    assert params['query'] == query and params['min_subject_lexemes'] == 2
    assert params['max_subject_document_fraction'] == 0.1
    assert "to_tsvector('english', coalesce(title, '') || ' ' || coalesce(post_details ->> 'tldr', ''))" in sql
    assert 'coalesce(publisher' in sql and 'NOT term = ANY(documents.publisher_lexemes)' in sql
    assert 'WHERE document_count = (SELECT min(document_count) FROM frequencies)' in sql
    assert 'FROM documents WHERE term = ANY(lexemes)' in sql  # Zero frequencies retained.
    assert 'documents.lexemes && subject.lexemes' in sql
    assert 'FROM distinctive WHERE term = ANY(documents.lexemes)' in sql
    assert 'WHERE to_tsvector' in sql and '@@ plainto_tsquery' in sql  # All words always qualify.
    assert 'new_match_count' in sql and sql.rstrip().endswith('FROM verified')
    assert 'LIMIT' not in sql.split('query_terms AS (', 1)[1]


@pytest.mark.parametrize('total,new,reason', [(7, 2, 'kept'), (3, 2, 'kept'), (0, 0, 'too_few_matches'),
    (1, 1, 'too_few_matches'), (2, 2, 'too_few_matches'), (7, 1, 'not_enough_new')])
def test_only_subject_qualified_counts_affect_admission_not_raw_any_word_matches(total, new, reason):
    service = state()
    service.sessions = SearchCounts([counts(0), counts(1), counts(total, new, raw_match_count=467)])
    result = suggest(service, [{'question': 'How does Snyk’s Evo remediation agent turn findings into pull requests?',
                                'check': {'query': 'Evo remediation agent pull requests Snyk'}}])
    decision = result['candidates'][0]
    assert decision['reason'] == reason and decision['kept'] == (reason == 'kept')
    assert decision['match_count'] == total and decision['new_match_count'] == new and decision['raw_match_count'] == 467
    assert decision['effective_query'] == 'Evo remediation agent pull requests Snyk'
    assert decision['effective_filters'] == {}  # Implicit relevance was relaxed.
    assert decision['check'] == {'query': 'Evo remediation agent pull requests Snyk'}


def test_publisher_without_a_question_subject_is_not_verified(monkeypatch):
    monkeypatch.setattr(followups, 'read_counts', lambda *args: pytest.fail('No subject to verify'))
    result = suggest(state(), [{'question': 'What has Hadrian published?', 'check': {'publisher': 'Hadrian'}}])
    assert result['candidates'][0]['reason'] == 'generic'
    assert result['candidates'][0]['effective_query'] == ''


def test_all_search_attempts_share_candidate_deadline(monkeypatch):
    db = SearchCounts([counts(0), counts(1)])
    times = iter([99, 99.75, 100.01])
    monkeypatch.setattr(followups.time, 'monotonic', lambda: next(times))
    with pytest.raises(TimeoutError):
        followups.read_counts(FollowUpPostCheck(query='ARTEX campaigns'), followups.SeenWorks(), db, 100)
    assert len(db.searches) == 2 and db.closed == 1
    assert [params['timeout'] for sql, params in db.calls if 'set_config' in sql] == ['1000', '250']


def test_paper_query_is_unchanged_and_auditable():
    check, audit = followups.effective_check(FollowUpCandidate(question='Which fuzzing benchmarks released code?', check='fuzzing'))
    assert check == 'fuzzing' and audit == {'effective_query': 'fuzzing', 'effective_filters': {'kind': 'paper'}}
