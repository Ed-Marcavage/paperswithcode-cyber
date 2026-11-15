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
from backend.services.assistant_posts import search_statement

MIN_FOLLOW_UP_MATCHES = 3
MIN_NEW_FOLLOW_UP_MATCHES = 2
MAX_FOLLOW_UPS = 3
FOLLOW_UP_SECONDS = 3
DESCRIPTION = """Call suggest_follow_ups ONCE at the end of research, before writing your
answer, with up to four useful, self-contained next questions and their checks.
A check is a find_posts filter object OR a short paper search phrase (string).
Verification needs at least three matches, two not already shown this turn.
Post checks use strict filters and all-word matching, without search fallbacks.
No topic carries over implicitly: name the needed subject in the question and check.
Good: narrow to a publisher/post type well represented in results; ask which
approaches released code when results showed code; explore newer work on a shown
subtopic or compare two approaches supported by results. Bad: generic questions,
unsupported promises, or repeating the visitor's question. Mention only kept
questions; do not mention rejected candidates. When there is nothing useful to
suggest, omit the tool or send an empty list."""


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
        def walk(value):
            if isinstance(value, list):
                for item in value:
                    walk(item)
            elif isinstance(value, dict):
                if 'title' in value or str(value.get('catalog_url', '')).startswith('/paper/'):
                    for key in ('id', 'paper_id', 'reference', 'arxiv_id', 'paper'):
                        if isinstance(value.get(key), (str, int)) and not isinstance(value[key], bool):
                            self.add(value[key])
                for key in ('results', 'items', 'data', 'paper', 'papers', 'discovery', 'top_trending_paper'):
                    if key in value:
                        walk(value[key])
        walk(payload)


STOP_WORDS = frozenset('a an the and or of to for from in on with about by as is are was were do does did can could should would i we me you it they their this that these those what which how why when where show tell find read learn more next other useful good best new newest recent latest work works paper papers post posts item items'.split())


def question_terms(question):
    words = re.findall(r'[^\W_]+', question.casefold())
    return {word[:-1] if len(word) > 4 and word.endswith('s') else word for word in words if word not in STOP_WORDS}


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
        timeout()
        if isinstance(check, str):
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
            statement, params = search_statement(check.model_dump(mode='json'), seen=seen)
            row = db.execute(statement, params).mappings().one()
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
            decision = {**candidate.model_dump(mode='json'), 'match_count': None, 'new_match_count': None, 'kept': False}
            reason = None
            if not self.researched:
                reason = 'no_research_evidence'
            else:
                try:
                    with anyio.fail_after(max(0, deadline - time.monotonic())):
                        counts = await anyio.to_thread.run_sync(read_counts, candidate.check, self.seen,
                                                               self.sessions, deadline, abandon_on_cancel=True)
                    decision.update(counts)
                except TimeoutError:
                    reason = 'deadline'
                except (SQLAlchemyError, OSError) as error:
                    # PostgreSQL statement_timeout cancels with 57014; report
                    # that deadline without exposing SQL or connection details.
                    reason = 'deadline' if getattr(getattr(error, 'orig', None), 'pgcode', None) == '57014' else 'verification_unavailable'
            if reason is None:
                if len(question_terms(candidate.question)) < 2 or isinstance(candidate.check, FollowUpPostCheck) and not any(
                    getattr(candidate.check, key) for key in ('query', 'topic', 'subtopic', 'post_type', 'publisher', 'harness_engineering', 'published_after')
                ):
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
