"""Data-checked follow-up suggestions; no model calls, MCP traffic or chat writes."""

import json
import re
import time
from dataclasses import dataclass, field
from difflib import SequenceMatcher

import anyio
from sqlalchemy import BigInteger, String, cast, column, func, or_, select, table, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import SQLAlchemyError

from backend.models.assistant_tools import FollowUpPostCheck, SuggestFollowUpsArguments
from backend.models.database import Paper as DBPaper
from backend.services.assistant_posts import ranked_search, search_statement
from backend.services.assistant_post_verification import SUBJECT_RULE

MIN_FOLLOW_UP_MATCHES = 3
MIN_NEW_FOLLOW_UP_MATCHES = 2
MAX_FOLLOW_UPS = 3
FOLLOW_UP_SECONDS = 3


@dataclass
class SeenWorks:
    ids: set[str] = field(default_factory=set)
    arxiv: set[str] = field(default_factory=set)

    def add(self, value):
        value = str(value)
        if re.fullmatch(r'[1-9][0-9]*', value):
            self.ids.add(value)
        elif match := re.fullmatch(r'([0-9]{4}\.[0-9]{4,5})(?:v[0-9]+)?', value):
            self.arxiv.add(match[1])

    def observe(self, result):
        # Only the bounded result actually supplied to the model, never hidden
        # raw rows. Catalog paths remain usable even in a byte-truncated result.
        for reference in re.findall(r'/paper/([0-9]+(?:\.[0-9]+)?(?:v[0-9]+)?)', result):
            self.add(reference)
        try:
            payload = json.loads(result)
        except ValueError:
            return
        for item in work_items(payload):
            for key in ('id', 'paper_id', 'reference', 'arxiv_id', 'paper'):
                if isinstance(item.get(key), (str, int)) and not isinstance(item[key], bool):
                    self.add(item[key])


def work_items(value):
    """Known work containers only; shared by novelty tracking and the digest."""
    if isinstance(value, list):
        for item in value:
            yield from work_items(item)
    elif isinstance(value, dict):
        if 'title' in value or str(value.get('catalog_url', '')).startswith('/paper/'):
            yield value
        for key in ('results', 'items', 'data', 'paper', 'papers', 'discovery', 'top_trending_paper'):
            if key in value:
                yield from work_items(value[key])



STOP_WORDS = frozenset('a an the and or of to for from in on with about by as is are was were do does did can could should would i we me you it they their this that these those what which how why when where show tell find read learn more next other useful good best new newest recent latest work works paper papers post posts item items'.split())


def question_terms(question):
    words = re.findall(r'[^\W_]+', question.casefold())
    return {word[:-1] if len(word) > 4 and word.endswith('s') else word for word in words if word not in STOP_WORDS}


# Search derivation is separate from near-duplicate normalization. Keep subject
# words (sandboxing, isolation, static analysis, etc.); strip question scaffolding
# and the publisher already expressed by an exact structured filter.
QUERY_STOP_WORDS = STOP_WORDS | frozenset('has have had been be being its our your their them us into inside through than then also s published publishes publish'.split())


def effective_check(candidate):
    check = candidate.check
    if isinstance(check, str):
        return check, {'effective_query': check, 'effective_filters': {'kind': 'paper'}}
    if not check.query:
        publisher_words = set(re.findall(r'[^\W_]+(?:-[^\W_]+)*', check.publisher.casefold()))
        excluded = QUERY_STOP_WORDS | publisher_words
        question = re.sub(r"['’]s\b", '', candidate.question.casefold())
        words = re.findall(r'[^\W_]+(?:-[^\W_]+)*', question)
        query = ' '.join(dict.fromkeys(word for word in words if word not in excluded))
        check = check.model_copy(update={'query': query})
    filters = {key: value for key, value in check.model_dump(mode='json').items()
               if key != 'query' and value is not None and value != ''}
    return check, {'effective_query': check.query, 'effective_filters': filters}


def near_duplicate(first, second):
    left, right = question_terms(first), question_terms(second)
    if left and right and len(left & right) / len(left | right) >= 0.75:
        return True
    def normalize(value):
        return ' '.join(re.findall(r'[^\W_]+', value.casefold()))
    return SequenceMatcher(None, normalize(first), normalize(second)).ratio() >= 0.88


def paper_count_statement(retrieval, phrase, seen):
    candidates = retrieval.keyword_candidates(phrase)
    works = table('discovery_works', column('paper_id', BigInteger), column('facets', JSONB))
    already_seen = or_(cast(DBPaper.id, String).in_(sorted(seen.ids)), func.coalesce(DBPaper.arxiv_id, '').in_(sorted(seen.arxiv)))
    return (select(func.count(func.distinct(DBPaper.id)).label('match_count'),
                   func.count(func.distinct(DBPaper.id)).filter(~already_seen).label('new_match_count'))
            .select_from(candidates).join(DBPaper, DBPaper.id == candidates.c.paper_id)
            .join(works, works.c.paper_id == DBPaper.id)
            .where(works.c.facets['kind'].op('?')('paper')).limit(1))


def read_counts(check, seen, sessions, deadline):
    if sessions is None:
        from backend.database.assistant import assistant_sessions
        sessions = assistant_sessions()
    with sessions() as db:
        db.execute(text('SET TRANSACTION READ ONLY'))
        def timeout():
            remaining = int((deadline - time.monotonic()) * 1000)
            if remaining <= 0:
                raise TimeoutError()
            db.execute(text("SELECT set_config('statement_timeout', :timeout, true)"), {'timeout': str(min(1000, remaining))})
        if isinstance(check, str):
            timeout()
            from backend.config import get_settings
            from backend.services.paper_retrieval_service import PaperRetrievalService
            retrieval = PaperRetrievalService(db, settings=get_settings(), summary_factory=lambda rows: rows,
                                              paper_resolver=lambda reference: None)
            # Reuse the existing keyword search with a one-item limit, then
            # count the same candidate relation for catalog papers and novelty.
            if not retrieval._search_papers_fts(check, limit=1):
                return {'match_count': 0, 'new_match_count': 0}
            timeout()
            row = db.execute(paper_count_statement(retrieval, check, seen)).mappings().one()
        else:
            # Preserve omission of the default: find_posts may relax an implicit
            # relevance filter, but never an explicit one or a structured filter.
            arguments = check.model_dump(mode='json', exclude_unset=True)
            def search(**options):
                timeout()
                statement, params = search_statement(arguments, seen=seen, **options)
                return dict(db.execute(statement, params).mappings().one())
            row, mode = ranked_search(arguments, search, lambda row: int(row['match_count']))
            filters = {key: value for key, value in check.model_dump(mode='json').items()
                       if key != 'query' and value is not None and value != ''}
            if mode['relevance_relaxed']:
                filters.pop('min_agent_relevance', None)
            return {**row, **mode, 'effective_filters': filters,
                    'subject_rule': SUBJECT_RULE if mode['match_mode'] == 'any_word' else 'all_words'}
        return {'match_count': int(row['match_count']), 'new_match_count': int(row['new_match_count'])}


class FollowUpState:
    def __init__(self, question='', sessions=None):
        self.question = question
        self.sessions = sessions
        self.seen = SeenWorks()
        self.researched = False
        self.used = False
        self.questions = []

    def observe(self, name, result):
        if name not in {'catalog_filters', 'suggest_follow_ups'} and not result.is_error:
            self.researched = True
            self.seen.observe(result.text)

    async def suggest(self, arguments):
        args = SuggestFollowUpsArguments.model_validate(arguments)
        if self.used:
            return {'follow_ups': self.questions.copy(), 'candidates': [], 'note': 'Already checked follow-ups this turn. Use only the kept questions.'}
        self.used = True
        deadline = time.monotonic() + FOLLOW_UP_SECONDS
        decisions = []
        for candidate in args.candidates:
            check, effective = effective_check(candidate)
            decision = {**candidate.model_dump(mode='json', exclude_unset=True), **effective,
                        'match_count': None, 'new_match_count': None, 'kept': False}
            reason = None
            if not self.researched:
                reason = 'no_research_evidence'
            elif isinstance(check, FollowUpPostCheck) and not check.query:
                reason = 'generic'
            else:
                try:
                    with anyio.fail_after(max(0, deadline - time.monotonic())):
                        counts = await anyio.to_thread.run_sync(read_counts, check, self.seen,
                                                               self.sessions, deadline, abandon_on_cancel=True)
                    decision.update(counts)
                except TimeoutError:
                    reason = 'deadline'
                except (SQLAlchemyError, OSError) as error:
                    # PostgreSQL statement_timeout cancels with 57014; report
                    # that deadline without exposing SQL or connection details.
                    reason = 'deadline' if getattr(getattr(error, 'orig', None), 'pgcode', None) == '57014' else 'verification_unavailable'
            if reason is None:
                if len(question_terms(candidate.question)) < 2:
                    reason = 'generic'
                elif near_duplicate(candidate.question, self.question):
                    reason = 'duplicate_question'
                elif any(near_duplicate(candidate.question, previous) for previous in self.questions):
                    reason = 'duplicate_candidate'
                elif decision['match_count'] < MIN_FOLLOW_UP_MATCHES:
                    reason = 'too_few_matches'
                elif decision['new_match_count'] < MIN_NEW_FOLLOW_UP_MATCHES:
                    reason = 'not_enough_new'
                elif len(self.questions) >= MAX_FOLLOW_UPS:
                    reason = 'limit'
                else:
                    reason = 'kept'
                    decision['kept'] = True
                    self.questions.append(candidate.question)
            decisions.append({**decision, 'reason': reason})
        return {'follow_ups': self.questions.copy(), 'candidates': decisions}
