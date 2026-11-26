"""Durability and retry tests for the local post-turn background worker."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from becoming.api_runtime import AppRuntime
from becoming.background import BackgroundWorker
from becoming.memory import SQLiteConversationStore
from becoming.long_memory import LongMemory
from becoming.models import ModelError
from becoming.personal_understanding import PersonalUnderstanding


class EmptyModel:
    def __init__(self, *, fail=False):
        self.calls = 0
        self.fail = fail

    def complete(self, messages):
        self.calls += 1
        if self.fail:
            raise ModelError("synthetic model outage")
        system = messages[0]["content"] if messages else ""
        if "你是个人理解更新引擎" in system:
            return json.dumps({
                "evidence": [], "operations": [], "confirmation": None,
            }, ensure_ascii=False)
        return "[]"


class BlockingModel:
    def __init__(self):
        import threading
        self.started = threading.Event()
        self.release = threading.Event()
        self.calls = 0

    def complete(self, messages):
        self.calls += 1
        if self.calls == 1:
            self.started.set()
            if not self.release.wait(5):
                raise ModelError("blocking model timed out")
        return "[]"


class BackgroundWorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp.name) / "conversations.sqlite3")

    def tearDown(self):
        self.temp.cleanup()

    def test_interrupted_jobs_are_recovered_and_extraction_is_idempotent(self):
        store = SQLiteConversationStore(self.db_path)
        turn_id = store.append_turn(
            "我今天去了公园。", "听起来不错。",
            background_jobs=(("long_memory.extract", 0),),
        )
        store.connection.execute(
            "UPDATE background_jobs SET status='running',attempts=1 WHERE source_turn_id=?",
            (turn_id,),
        )
        store.connection.commit()
        store.close()

        model = EmptyModel()
        worker = BackgroundWorker(
            self.db_path, lambda: model,
            enable_long_memory=True,
            enable_personal_understanding=False,
        )
        try:
            pending = worker.db.execute(
                "SELECT status FROM background_jobs WHERE source_turn_id=?",
                (turn_id,),
            ).fetchone()[0]
            self.assertEqual(pending, "pending")
            self.assertTrue(worker.run_once())
            status = worker.db.execute(
                "SELECT status,attempts FROM background_jobs WHERE source_turn_id=?",
                (turn_id,),
            ).fetchone()
            self.assertEqual(status, ("done", 2))
            self.assertEqual(model.calls, 1)

            # Simulate a crash after the durable receipt but before the queue
            # acknowledgement. Replaying extraction must not call the model twice.
            replay = worker.long_memory.extract(turn_id, "我今天去了公园。")
            self.assertEqual(replay, ())
            self.assertEqual(model.calls, 1)
            self.assertEqual(
                worker.db.execute(
                    "SELECT COUNT(*) FROM long_memory_extraction_receipts WHERE turn_id=?",
                    (turn_id,),
                ).fetchone()[0],
                1,
            )
        finally:
            worker.stop()

    def test_exhausted_interrupted_job_becomes_failed_after_restart(self):
        store = SQLiteConversationStore(self.db_path)
        turn_id = store.append_turn(
            "这条任务在第三次尝试时中断。", "明白。",
            background_jobs=(("long_memory.extract", 0),),
        )
        store.connection.execute(
            "UPDATE background_jobs SET status='running',attempts=3 WHERE source_turn_id=?",
            (turn_id,),
        )
        store.connection.commit()
        store.close()

        worker = BackgroundWorker(
            self.db_path, lambda: EmptyModel(),
            enable_long_memory=True,
            enable_personal_understanding=False,
        )
        try:
            status, error, attempts = worker.db.execute(
                "SELECT status,last_error,attempts FROM background_jobs WHERE source_turn_id=?",
                (turn_id,),
            ).fetchone()
            self.assertEqual(status, "failed")
            self.assertEqual(error, "attempts_exhausted_after_restart")
            self.assertEqual(attempts, 3)
            self.assertFalse(worker.run_once())
        finally:
            worker.stop()

    def test_durable_receipts_reconcile_jobs_completed_before_crash(self):
        store = SQLiteConversationStore(self.db_path)
        memory_turn = store.append_turn(
            "我喜欢阅读。", "明白。",
            background_jobs=(("long_memory.extract", 0),),
        )
        understanding_turn = store.append_turn(
            "我重视自由。", "明白。",
            background_jobs=(("personal_understanding.process", 0),),
        )
        model = EmptyModel()
        LongMemory(store, model)
        PersonalUnderstanding(store, model, recover_running_jobs=False)._enqueue(
            understanding_turn, "normal"
        )
        store.connection.execute(
            "INSERT INTO long_memory_extraction_receipts(turn_id) VALUES(?)",
            (memory_turn,),
        )
        store.connection.execute(
            "UPDATE understanding_jobs SET status='done' WHERE source_turn_id=?",
            (understanding_turn,),
        )
        store.connection.execute(
            "UPDATE background_jobs SET status='running',attempts=3 WHERE source_turn_id IN (?,?)",
            (memory_turn, understanding_turn),
        )
        store.connection.commit()
        store.close()

        worker = BackgroundWorker(
            self.db_path, lambda: model,
            enable_long_memory=True,
            enable_personal_understanding=True,
        )
        try:
            statuses = worker.db.execute(
                "SELECT source_turn_id,status FROM background_jobs ORDER BY source_turn_id"
            ).fetchall()
            self.assertEqual(
                statuses,
                [(memory_turn, "done"), (understanding_turn, "done")],
            )
            self.assertFalse(worker.run_once())
        finally:
            worker.stop()

    def test_failed_jobs_retry_three_times_then_stop(self):
        store = SQLiteConversationStore(self.db_path)
        turn_id = store.append_turn(
            "我喜欢安静的环境。", "明白。",
            background_jobs=(("long_memory.extract", 0),),
        )
        store.close()

        model = EmptyModel(fail=True)
        worker = BackgroundWorker(
            self.db_path, lambda: model,
            enable_long_memory=True,
            enable_personal_understanding=False,
        )
        try:
            for attempt in range(1, 4):
                if attempt > 1:
                    worker.db.execute(
                        "UPDATE background_jobs SET available_at=0 WHERE source_turn_id=?",
                        (turn_id,),
                    )
                    worker.db.commit()
                self.assertTrue(worker.run_once())
                status, attempts = worker.db.execute(
                    "SELECT status,attempts FROM background_jobs WHERE source_turn_id=?",
                    (turn_id,),
                ).fetchone()
                self.assertEqual(attempts, attempt)
                self.assertEqual(status, "failed" if attempt == 3 else "pending")
            self.assertFalse(worker.run_once())
            self.assertEqual(model.calls, 3)
        finally:
            worker.stop()

    def test_source_conversation_deletion_cascades_pending_tasks(self):
        store = SQLiteConversationStore(self.db_path)
        conversation = store.create_conversation("待删除会话")
        scoped = store.for_conversation(conversation["id"])
        turn_id = scoped.append_turn(
            "我喜欢安静的环境。", "明白。",
            background_jobs=(
                ("long_memory.extract", 0),
                ("personal_understanding.process", 0),
            ),
        )
        self.assertEqual(
            store.connection.execute(
                "SELECT COUNT(*) FROM background_jobs WHERE source_turn_id=?",
                (turn_id,),
            ).fetchone()[0],
            2,
        )
        store.delete_conversation(conversation["id"])
        self.assertEqual(
            store.connection.execute(
                "SELECT COUNT(*) FROM background_jobs WHERE source_turn_id=?",
                (turn_id,),
            ).fetchone()[0],
            0,
        )
        store.close()

    def test_pause_waits_for_active_job_and_prevents_new_claims(self):
        import threading

        store = SQLiteConversationStore(self.db_path)
        first_turn = store.append_turn(
            "第一条用于暂停测试。", "明白。",
            background_jobs=(("long_memory.extract", 0),),
        )
        model = BlockingModel()
        worker = BackgroundWorker(
            self.db_path, lambda: model,
            enable_long_memory=True,
            enable_personal_understanding=False,
        )
        runner = threading.Thread(target=worker.run_once)
        try:
            runner.start()
            self.assertTrue(model.started.wait(2))
            self.assertFalse(worker.pause(timeout=0.02))
            model.release.set()
            runner.join(timeout=3)
            self.assertFalse(runner.is_alive())
            self.assertTrue(worker.pause(timeout=1))

            second_turn = store.append_turn(
                "第二条用于验证暂停。", "明白。",
                background_jobs=(("long_memory.extract", 0),),
            )
            self.assertFalse(worker.run_once())
            self.assertEqual(
                worker.db.execute(
                    "SELECT status FROM background_jobs WHERE source_turn_id=?",
                    (second_turn,),
                ).fetchone()[0],
                "pending",
            )
            worker.resume()
            self.assertTrue(worker.run_once())
            self.assertEqual(
                worker.db.execute(
                    "SELECT status FROM background_jobs WHERE source_turn_id=?",
                    (second_turn,),
                ).fetchone()[0],
                "done",
            )
        finally:
            model.release.set()
            runner.join(timeout=3)
            worker.resume()
            worker.stop()
            store.close()

    def test_jobs_are_cancelled_when_their_feature_is_disabled(self):
        store = SQLiteConversationStore(self.db_path)
        turn_id = store.append_turn(
            "我喜欢安静的环境。", "明白。",
            background_jobs=(("long_memory.extract", 0),),
        )
        store.close()

        worker = BackgroundWorker(
            self.db_path, lambda: None,
            enable_long_memory=False,
            enable_personal_understanding=False,
        )
        try:
            self.assertFalse(worker.run_once())
            status, error = worker.db.execute(
                "SELECT status,last_error FROM background_jobs WHERE source_turn_id=?",
                (turn_id,),
            ).fetchone()
            self.assertEqual(status, "cancelled")
            self.assertEqual(error, "feature_disabled")
            self.assertIsNone(worker.last_error)
        finally:
            worker.stop()

    def test_jobs_wait_without_consuming_attempts_until_model_is_configured(self):
        store = SQLiteConversationStore(self.db_path)
        turn_id = store.append_turn(
            "模型暂未配置时仍要保留任务。", "稍后整理。",
            background_jobs=(("long_memory.extract", 0),),
        )
        store.close()

        model = EmptyModel()
        configured = {"model": None}
        worker = BackgroundWorker(
            self.db_path, lambda: configured["model"],
            enable_long_memory=True,
            enable_personal_understanding=False,
        )
        try:
            self.assertFalse(worker.run_once())
            status, attempts = worker.db.execute(
                "SELECT status,attempts FROM background_jobs WHERE source_turn_id=?",
                (turn_id,),
            ).fetchone()
            self.assertEqual((status, attempts), ("pending", 0))
            self.assertEqual(worker.last_error, "model_not_configured")

            configured["model"] = model
            worker.set_model(model)
            self.assertTrue(worker.run_once())
            status, attempts = worker.db.execute(
                "SELECT status,attempts FROM background_jobs WHERE source_turn_id=?",
                (turn_id,),
            ).fetchone()
            self.assertEqual((status, attempts), ("done", 1))
            self.assertEqual(model.calls, 1)
        finally:
            worker.stop()

    def test_in_memory_runtime_reports_stable_status_without_worker(self):
        runtime = AppRuntime(
            db_path=":memory:", growth_db_path=":memory:", model=EmptyModel()
        )
        try:
            status = runtime.background_status()
            self.assertFalse(status["supported"])
            self.assertFalse(status["running"])
            self.assertFalse(status["paused"])
            self.assertEqual(status["active_jobs"], 0)
            self.assertEqual(status["counts"]["pending"], 0)
        finally:
            runtime.close()

    def test_personal_understanding_jobs_run_off_the_request_path(self):
        store = SQLiteConversationStore(self.db_path)
        turn_id = store.append_turn(
            "我更在意能自己安排时间。", "我会记住这个重要的偏好。",
            background_jobs=(("personal_understanding.process", 10),),
        )
        store.close()

        model = EmptyModel()
        worker = BackgroundWorker(
            self.db_path, lambda: model,
            enable_long_memory=False,
            enable_personal_understanding=True,
        )
        try:
            self.assertTrue(worker.run_once())
            generic = worker.db.execute(
                "SELECT status FROM background_jobs WHERE source_turn_id=?",
                (turn_id,),
            ).fetchone()[0]
            internal = worker.db.execute(
                "SELECT status FROM understanding_jobs WHERE job_key=?",
                (f"turn:{turn_id}",),
            ).fetchone()[0]
            self.assertEqual(generic, "done")
            self.assertEqual(internal, "done")
            self.assertEqual(model.calls, 1)
        finally:
            worker.stop()


if __name__ == "__main__":
    unittest.main()
