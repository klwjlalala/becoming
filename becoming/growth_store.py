"""Local, single-user growth records. Independent of transcript and semantic memory."""
from __future__ import annotations

import sqlite3
from pathlib import Path


TOOLS = {
    "list_goals": (set(), {"offset"}),
    "get_goal": ({"goal_id"}, {"offset"}),
    "create_goal": ({"text"}, set()),
    "create_action": ({"goal_id", "text"}, set()),
    "record_reflection": ({"goal_id", "text"}, set()),
    "update_item": ({"id"}, {"text", "status"}),
    "delete_item": ({"id"}, set()),
}
READ_TOOLS = frozenset(("list_goals", "get_goal"))
PAGE_SIZE = 30
STATUSES = {"goal": {"active", "paused", "completed"},
            "action": {"pending", "done", "skipped"}}


def validate(tool, args):
    if not isinstance(tool, str) or tool not in TOOLS or not isinstance(args, dict):
        raise ValueError("Unknown tool or invalid arguments")
    required, optional = TOOLS[tool]
    if not required <= args.keys() or args.keys() - required - optional:
        raise ValueError("Missing or unexpected arguments")
    clean = dict(args)
    for key, value in clean.items():
        if key in ("id", "goal_id", "offset"):
            if type(value) is not int or not (0 if key == "offset" else 1) <= value <= 2**31 - 1:
                raise ValueError("Invalid " + key)
        elif key == "text":
            if not isinstance(value, str) or not value.strip() or len(value) > 2000:
                raise ValueError("Text must contain 1–2000 characters")
            clean[key] = value.strip()
        elif key == "status":
            if not isinstance(value, str) or value not in set().union(*STATUSES.values()):
                raise ValueError("Invalid status")
    if tool == "update_item" and not ({"text", "status"} & clean.keys()):
        raise ValueError("At least one change is required")
    return clean


class GrowthStore:
    def __init__(self, path: str | Path = "data/growth.sqlite3"):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(str(path))
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        with self.connection:
            self.connection.execute("""
                CREATE TABLE IF NOT EXISTS growth_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    kind TEXT NOT NULL CHECK(kind IN ('goal','action','reflection')),
                    goal_id INTEGER REFERENCES growth_items(id) ON DELETE CASCADE,
                    text TEXT NOT NULL CHECK(length(trim(text)) > 0 AND length(text) <= 2000),
                    status TEXT NOT NULL,
                    version INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    CHECK((kind='goal' AND goal_id IS NULL AND status IN ('active','paused','completed'))
                       OR (kind='action' AND goal_id IS NOT NULL AND status IN ('pending','done','skipped'))
                       OR (kind='reflection' AND goal_id IS NOT NULL AND status='recorded'))
                )
            """)
            self.connection.execute("CREATE INDEX IF NOT EXISTS growth_parent ON growth_items(goal_id, id)")

    def clear(self):
        """Delete all growth goals; child actions and reflections cascade."""
        counts = {row["kind"]: row["count"] for row in self.connection.execute(
            "SELECT kind, COUNT(*) AS count FROM growth_items GROUP BY kind")}
        with self.connection:
            self.connection.execute("DELETE FROM growth_items WHERE kind='goal'")
        return {kind: counts.get(kind, 0) for kind in ("goal", "action", "reflection")}

    def close(self):
        self.connection.close()

    def _item(self, item_id):
        row = self.connection.execute("SELECT * FROM growth_items WHERE id=?", (item_id,)).fetchone()
        if row is None:
            raise ValueError("Record not found")
        return dict(row)

    def _goal(self, goal_id):
        item = self._item(goal_id)
        if item["kind"] != "goal":
            raise ValueError("Expected a goal ID")
        return item

    def read(self, tool, args):
        args = validate(tool, args)
        if tool not in READ_TOOLS:
            raise ValueError("Not a read tool")
        offset = args.get("offset", 0)
        if tool == "list_goals":
            where, params = "kind='goal'", ()
            parent = None
        else:
            parent = self._goal(args["goal_id"])
            where, params = "goal_id=?", (args["goal_id"],)
        # SQL fragments above are constants; only bound parameters contain user data.
        rows = self.connection.execute(
            "SELECT * FROM growth_items WHERE " + where + " ORDER BY id LIMIT ? OFFSET ?",
            (*params, PAGE_SIZE + 1, offset)).fetchall()
        return {"goal": parent, "items": [dict(r) for r in rows[:PAGE_SIZE]],
                "next_offset": offset + PAGE_SIZE if len(rows) > PAGE_SIZE else None}

    def prepare(self, tool, args):
        """Validate a mutation and capture the exact state presented for approval."""
        args = validate(tool, args)
        if tool in READ_TOOLS:
            raise ValueError("Not a mutation")
        preview = {"tool": tool, "args": args}
        if tool in ("create_action", "record_reflection"):
            preview["parent"] = self._goal(args["goal_id"])
        if tool in ("update_item", "delete_item"):
            before = self._item(args["id"])
            preview["before"] = before
            if tool == "update_item" and "status" in args:
                if args["status"] not in STATUSES.get(before["kind"], set()):
                    raise ValueError("Status not permitted for record kind")
            if tool == "delete_item" and before["kind"] == "goal":
                # Include exact child versions so changed/deleted/added children invalidate approval.
                preview["children"] = [dict(r) for r in self.connection.execute(
                    "SELECT id, kind, version FROM growth_items WHERE goal_id=? ORDER BY id",
                    (before["id"],))]
        return preview

    def apply(self, preview):
        """Revalidate under write lock; atomic mutation, no silent stale approval."""
        tool, args = preview["tool"], preview["args"]
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            if self.prepare(tool, args) != preview:
                raise ValueError("Record changed; request a new proposal")
            if tool in ("create_goal", "create_action", "record_reflection"):
                kind, status = {"create_goal": ("goal", "active"),
                                "create_action": ("action", "pending"),
                                "record_reflection": ("reflection", "recorded")}[tool]
                cursor = self.connection.execute(
                    "INSERT INTO growth_items(kind,goal_id,text,status) VALUES(?,?,?,?)",
                    (kind, args.get("goal_id"), args["text"], status))
                result = {"record": self._item(cursor.lastrowid)}
            elif tool == "update_item":
                old = preview["before"]
                self.connection.execute(
                    "UPDATE growth_items SET text=?,status=?,version=version+1,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (args.get("text", old["text"]), args.get("status", old["status"]), old["id"]))
                result = {"record": self._item(old["id"])}
            else:
                self.connection.execute("DELETE FROM growth_items WHERE id=?", (args["id"],))
                result = {"deleted_id": args["id"], "deleted_children": len(preview.get("children", []))}
            self.connection.commit()
            return result
        except BaseException:
            self.connection.rollback()
            raise
