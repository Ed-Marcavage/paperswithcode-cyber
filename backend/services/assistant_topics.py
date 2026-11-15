"""Public topic choices and per-turn scoping for the catalog assistant."""

import json
import threading
import time
from copy import deepcopy
from weakref import WeakKeyDictionary

from sqlalchemy import text

from backend.services.trending_posts import MIN_AGENT_RELEVANCE

MIN_TOPIC_WORKS = 20
TOPICS_CACHE_SECONDS = 300
TOPICS_PUBLIC_MAX_AGE = 60
TOPIC_CACHE = WeakKeyDictionary()
TOPIC_LOCK = threading.Lock()
TOPICS_SQL = text("""
    SELECT t.value AS slug, t.label, count(DISTINCT w.paper_id) AS count
      FROM discovery_works w
      CROSS JOIN LATERAL jsonb_array_elements_text(w.facets -> 'topic') AS topic(value)
      JOIN discovery_terms t ON t.axis = 'topic' AND t.value = topic.value
     WHERE w.facets -> 'kind' ? 'paper'
        OR (w.facets -> 'kind' ? 'post'
            AND coalesce((w.post_details ->> 'agent_relevance')::integer, 0) >= :min_relevance)
     GROUP BY t.value, t.label
""")


class UnknownTopic(ValueError):
    pass


def topic_choices(rows):
    return sorted(({"slug": row["slug"], "label": row["label"], "count": int(row["count"])}
                   for row in rows if int(row["count"]) >= MIN_TOPIC_WORKS),
                  key=lambda row: (-row["count"], row["slug"]))


def get_topics(sessions=None):
    if sessions is None:
        from backend.database.assistant import assistant_sessions
        sessions = assistant_sessions()
    with TOPIC_LOCK:
        cached = TOPIC_CACHE.get(sessions)
        if cached and cached[0] > time.monotonic():
            return deepcopy(cached[1])
        with sessions() as db:
            db.execute(text("SET TRANSACTION READ ONLY"))
            db.execute(text("SELECT set_config('statement_timeout', :timeout, true)"), {"timeout": "1500"})
            result = topic_choices(db.execute(TOPICS_SQL, {"min_relevance": MIN_AGENT_RELEVANCE}).mappings())
        TOPIC_CACHE[sessions] = (time.monotonic() + TOPICS_CACHE_SECONDS, result)
        return deepcopy(result)


def resolve_topic(slug, sessions=None):
    if slug is None:
        return None
    for topic in get_topics(sessions):
        if topic["slug"] == slug:
            return topic
    raise UnknownTopic("Unknown topic. Choose one of the available topics.")


def topic_instruction(topic):
    if topic is None:
        return None
    return (f"The visitor chose topic {json.dumps(topic['label'])} ({topic['slug']}). "
            "Scope searches to it unless the question clearly asks otherwise. "
            'For find_posts and browse_catalog, omit topic to use this choice; send topic="" to search across topics.')


def scoped_result(result, topic):
    from backend.services.assistant_mcp import ToolResult, cap_payload, MAX_RESULT_BYTES
    scope = {"topic": topic["slug"], "label": topic["label"], "defaulted": True}
    try:
        payload = json.loads(result.text)
    except ValueError:
        payload = None
    if isinstance(payload, dict):
        payload = {**payload, "scope": scope}
        wrapped = cap_payload(payload, limit=MAX_RESULT_BYTES, is_json=True, is_error=result.is_error)
        return wrapped
    note = f"[Topic scope defaulted to {topic['label']} ({topic['slug']}).]\n"
    wrapped = cap_payload(note + result.text, limit=MAX_RESULT_BYTES, is_json=False, is_error=result.is_error)
    return ToolResult(wrapped.text, result.full_bytes + len(note.encode()), result.truncated or wrapped.truncated, result.is_error)
