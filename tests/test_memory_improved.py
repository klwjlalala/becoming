import io
import json
import unittest
from unittest.mock import patch

from becoming.agent import Agent
from becoming.embeddings import OpenAICompatibleEmbedder, hybrid_pool
from becoming.long_memory import Memory
from becoming.memory import SQLiteConversationStore
from becoming.memory_improved import ImprovedMemory
from becoming.models import ModelError
from test_long_memory import ScriptedModel


def plan():
    return json.dumps({"topics":["个人活动"],"start":None,"end":None,"include_history":False})


class ImprovedTests(unittest.TestCase):
    def setUp(self):
        self.store = SQLiteConversationStore(":memory:")
        self.addCleanup(self.store.close)

    def add(self, memory, key, quote, category="fact"):
        turn = self.store.append_turn(quote, "好")
        return memory.write(turn, [(key, category, quote)])[0]

    def test_all_fifty_candidates_and_final_rank(self):
        memory = ImprovedMemory(self.store, ScriptedModel())
        ids = [self.add(memory, f"item{i}", f"记录编号{i}") for i in range(50)]
        class Selector:
            def complete(self, messages):
                p = json.loads(messages[1]["content"])
                if "candidates" not in p:
                    return plan()
                return json.dumps([x["id"] for x in p["candidates"] if x["id"] in (ids[1],ids[2],ids[3],ids[-1])])
        memory.model = Selector()
        chosen = memory.retrieve("活动")
        self.assertEqual({m.id for m in chosen}, {ids[1],ids[2],ids[3],ids[-1]})
        self.assertEqual(len(memory.last_search["candidate_ids"]),50)
        self.assertEqual(len(memory.last_search["batches"]),2)
        self.assertFalse(memory.last_search["truncated"])

    def test_scan_cap_and_invalid_second_batch_fail_closed(self):
        memory = ImprovedMemory(self.store, ScriptedModel())
        for i in range(165):
            self.add(memory, f"item{i}", f"编号{i}")
        memory.model = ScriptedModel(plan(), "[]", "[999999]", "正常回复", "[]")
        agent = Agent(memory.model,self.store,history_turns=0,long_memory=memory)
        self.assertEqual(agent.reply("活动"),"正常回复")
        self.assertEqual(agent.last_memory_event.errors,("retrieve_failed",))
        self.assertEqual(len(memory.last_search["candidate_ids"]),160)
        self.assertTrue(memory.last_search["truncated"])

    def test_supplement_and_explicit_correction(self):
        memory = ImprovedMemory(self.store, ScriptedModel())
        old = self.add(memory,"venue","我不喜欢拥挤嘈杂的场所。","subjective")
        sport = self.add(memory,"sport","我最喜欢跑步。","subjective")
        data = [{"key":"social","category":"subjective","quote":"我不是完全排斥社交，只是不喜欢很吵的环境。","replaces":None}]
        memory.model = ScriptedModel(json.dumps(data))
        turn = self.store.append_turn(data[0]["quote"],"好")
        self.assertTrue(memory.extract(turn,data[0]["quote"]))
        self.assertIn(old,[m.id for m in memory.list_active()])
        change = "我之前说错了：我最喜欢游泳，不是跑步。"
        memory.model = ScriptedModel(json.dumps([{"key":"sport","category":"subjective","quote":change,"replaces":sport}]))
        turn = self.store.append_turn(change,"好")
        self.assertTrue(memory.extract(turn,change))
        self.assertNotIn(sport,[m.id for m in memory.list_active()])

    def test_ambiguous_replacement_cannot_invalidate_old(self):
        memory = ImprovedMemory(self.store, ScriptedModel())
        old = self.add(memory,"venue","我不喜欢拥挤嘈杂的场所。","subjective")
        quote = "我不是完全排斥社交，只是不喜欢很吵的环境。"
        memory.model = ScriptedModel(json.dumps([{"key":"venue","category":"subjective","quote":quote,"replaces":old}]))
        turn = self.store.append_turn(quote,"好")
        with self.assertRaises(ValueError):
            memory.extract(turn,quote)
        self.assertEqual([m.id for m in memory.list_active()],[old])

    def test_hybrid_semantic_zero_overlap_and_fallback(self):
        items = [Memory(i+1,f"item{i}","fact",f"编号{i}",i+1) for i in range(45)]
        class Fake:
            def embed(self,texts):
                return [[1,0] if i < 2 or i == 2 else [0,1] for i in range(len(texts))]
        pool = hybrid_pool(items,"活动",("个人活动",),Fake(),40)
        self.assertIn(1,[m.id for m in pool])
        self.assertEqual(len({m.id for m in pool}),40)
        class Broken:
            def embed(self,texts):
                raise ModelError("unavailable")
        memory = ImprovedMemory(self.store,ScriptedModel(plan(),"[]","[]"),embedder=Broken())
        for i in range(45):
            self.add(memory,f"item{i}",f"编号{i}")
        self.assertEqual(memory.retrieve("活动"),[])
        self.assertTrue(memory.last_search["embedding_fallback"])
        self.assertEqual(len(memory.last_search["candidate_ids"]),45)

    def test_embedding_wire_and_bad_indices(self):
        embedder = OpenAICompatibleEmbedder("https://example.test/v1","fake","embed")
        with patch("becoming.embeddings.urlopen",return_value=io.BytesIO(json.dumps({"data":[
            {"index":1,"embedding":[0,2]},{"index":0,"embedding":[3,0]}]}).encode())) as send:
            self.assertEqual(embedder.embed(["甲","乙"]),[(1.,0.),(0.,1.)])
            self.assertEqual(send.call_args.args[0].full_url,"https://example.test/v1/embeddings")
            self.assertEqual(json.loads(send.call_args.args[0].data)["input"],["甲","乙"])
        with patch("becoming.embeddings.urlopen",return_value=io.BytesIO(b'{"data":[{"index":1,"embedding":[1]}]}')):
            with self.assertRaises(ModelError):
                embedder.embed(["甲"])
