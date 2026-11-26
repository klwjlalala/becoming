"""V1.4 experimental retrieval and conservative revision policy.

No background jobs, no schema change. Scan small histories in bounded batches;
optional embeddings are a replaceable, explicitly configured experiment.
"""
from dataclasses import asdict
import re

from .long_memory import EXTRACT_PROMPT, SECRET, SEMANTIC_POOL
from .memory_search import ComprehensiveMemory, candidate_pool
from .models import ModelError
from .embeddings import hybrid_pool

SCAN_LIMIT = 160
VECTOR_LIMIT = 512
# Heuristic gate, not proof of contradiction. A model must still verify scope.
REVISION_CUE = re.compile(
    r"之前说错|以前说错|刚才说错|更正|纠正|记错|不再|已经变了|改成|改为|"
    r"现在(?:是|在)|(?:used to|no longer|actually|i was wrong|correction|changed to)\b", re.I)
REVISION_PROMPT = EXTRACT_PROMPT + """
特别注意：补充、细化、不同条件下的偏好，不是纠正。仅在用户明确纠正或明确改变旧信息、
且新原话足以替代该槽位的全部旧含义时使用 replaces。旧记录含有新句未否定的独立信息时，
必须保留旧记录，新增粒度更细的独立 key，replaces=null。例如旧句“不喜欢拥挤嘈杂的场所”，
新句“我不是完全排斥社交，只是不喜欢很吵的环境”，应新增社交偏好，不能覆盖场所偏好。
不要因为主题相同就替换。若无法确定矛盾，保留旧证据，新增明确且非重复的独立信息；
完全重复则不写。明确更正原来的最爱运动或工作单位时才更新对应槽位。
"""


class ImprovedMemory(ComprehensiveMemory):
    def __init__(self, store, model, *, embedder=None):
        super().__init__(store, model)
        self.embedder = embedder

    def extraction_prompt(self):
        return REVISION_PROMPT

    def validate_extracted_revision(self, candidate, user):
        key, category, quote, replaces = candidate
        # Only the actual proposed quote may justify invalidating the old record.
        # If ambiguous, reject this item (extract_partial/failed), never silently
        # invalidate an old record or invent a new slot name.
        if replaces is not None and not REVISION_CUE.search(quote):
            old = self.db.execute("SELECT category,quote FROM long_memories WHERE id=? AND active=1",
                                  (replaces,)).fetchone()
            if old != (category, quote):
                raise ValueError("ambiguous memory replacement")

    def retrieve(self, query, limit=8):
        self.last_search = None
        if type(limit) is not int or not 0 <= limit <= 10:
            raise ValueError("invalid memory limit")
        if not limit or not query.strip() or SECRET.search(query):
            return []
        if not self.db.execute("SELECT 1 FROM long_memories LIMIT 1").fetchone():
            return []
        plan = self.plan_query(query)
        items = self.eligible(plan)
        trace = {"plan": asdict(plan), "eligible_count": len(items), "candidate_ids": (),
                 "strategy": "bounded_scan", "batches": [], "shortlisted_ids": ()}
        self.last_search = trace
        if not items:
            return []
        # Embeddings are optional and never silently substitute an unconfigured model.
        if self.embedder is not None and len(items) <= VECTOR_LIMIT:
            try:
                pool = hybrid_pool(items, query, plan.topics, self.embedder, SEMANTIC_POOL)
            except (ModelError, ValueError):
                trace["embedding_fallback"] = True
            else:
                trace["strategy"] = "hybrid_embedding"
                trace["candidate_ids"] = tuple(m.id for m in pool)
                return self.rank(query, plan, pool, limit)
        elif self.embedder is not None:
            trace["embedding_fallback"] = True
            trace["embedding_limit_exceeded"] = True
        pool = candidate_pool(items, plan.topics, min(len(items), SCAN_LIMIT))
        trace["candidate_ids"] = tuple(m.id for m in pool)
        trace["truncated"] = len(items) > len(pool)
        if len(pool) <= SEMANTIC_POOL:
            return self.rank(query, plan, pool, limit)
        shortlisted = []
        for start in range(0, len(pool), SEMANTIC_POOL):
            batch = pool[start:start + SEMANTIC_POOL]
            chosen = self.rank(query, plan, batch, limit)
            trace["batches"].append({"candidate_ids": tuple(m.id for m in batch),
                                     "selected_ids": tuple(m.id for m in chosen)})
            shortlisted.extend(chosen)
        trace["shortlisted_ids"] = tuple(m.id for m in shortlisted)
        # At most 4 batches * 10 candidates = 40. Final global ranking keeps
        # independent per-batch selection from arbitrarily ordering the response.
        return self.rank(query, plan, shortlisted, limit)
