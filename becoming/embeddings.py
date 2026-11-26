"""Small opt-in OpenAI-compatible embedding experiment; no persistent vector cache."""
import json
import math
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from .models import OpenAICompatibleModel, ModelError
from .long_memory import terms

BATCH_SIZE = 32
MAX_DIM = 8192


def unit(vector):
    if (not isinstance(vector, (list, tuple)) or not 0 < len(vector) <= MAX_DIM or
        any(type(x) not in (int, float) or not math.isfinite(x) for x in vector)):
        raise ValueError("invalid embedding vector")
    norm = math.hypot(*vector)
    if not norm or not math.isfinite(norm):
        raise ValueError("invalid embedding norm")
    return tuple(x / norm for x in vector)


class OpenAICompatibleEmbedder:
    def __init__(self, base_url, api_key, model, timeout=60):
        # Reuse the existing URL and credential validation boundary.
        checked = OpenAICompatibleModel(base_url, api_key, model, timeout)
        self.url = checked.url.removesuffix("/chat/completions") + "/embeddings"
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.calls = 0

    def embed(self, texts):
        result = []
        for offset in range(0, len(texts), BATCH_SIZE):
            batch = texts[offset:offset+BATCH_SIZE]
            request = Request(self.url,
                              data=json.dumps({"model": self.model, "input": batch},
                                              ensure_ascii=False).encode("utf-8"),
                              headers={"Authorization": "Bearer " + self.api_key,
                                       "Content-Type": "application/json"}, method="POST")
            self.calls += 1
            try:
                with urlopen(request, timeout=self.timeout) as response:
                    payload = json.load(response)
                data = payload["data"]
                if not isinstance(data, list) or len(data) != len(batch):
                    raise ValueError("invalid embedding batch")
                by_index = {}
                for row in data:
                    index = row["index"]
                    if type(index) is not int or not 0 <= index < len(batch) or index in by_index:
                        raise ValueError("invalid embedding index")
                    by_index[index] = unit(row["embedding"])
                result.extend(by_index[i] for i in range(len(batch)))
            except HTTPError as exc:
                raise ModelError(f"Embedding request failed (HTTP {exc.code})") from None
            except (URLError, OSError, TimeoutError):
                raise ModelError("Embedding connection failed") from None
            except (ValueError, KeyError, TypeError, IndexError, OverflowError):
                raise ModelError("Invalid embedding response") from None
        return result


def hybrid_pool(items, query, topics, embedder, limit):
    """Per-topic round-robin semantic ranks with lexical rank as another channel."""
    if len(items) <= limit:
        return list(items)
    questions = [query, *topics]
    inputs = questions + [f"{m.key}: {m.quote}" for m in items]
    raw = embedder.embed(inputs)
    if len(raw) != len(inputs):
        raise ValueError("invalid embedding count")
    vectors = [unit(v) for v in raw]
    if len({len(v) for v in vectors}) != 1:
        raise ValueError("inconsistent embedding dimensions")
    qvecs, mvecs = vectors[:len(questions)], vectors[len(questions):]
    ranks = [iter(sorted(range(len(items)),
                         key=lambda i: (sum(a*b for a,b in zip(qv,mvecs[i])), items[i].id),
                         reverse=True)) for qv in qvecs]
    qterms = terms(" ".join(questions))
    scores = [3 * len(qterms & terms(m.key)) + len(qterms & terms(m.quote)) for m in items]
    ranks.append(iter(sorted((i for i,s in enumerate(scores) if s),
                             key=lambda i: (scores[i], items[i].id), reverse=True)))
    seen, pool = set(), []
    while ranks and len(pool) < limit:
        remaining = []
        for it in ranks:
            for i in it:
                if i not in seen:
                    seen.add(i)
                    pool.append(items[i])
                    remaining.append(it)
                    break
            if len(pool) == limit:
                break
        ranks = remaining
    return pool
