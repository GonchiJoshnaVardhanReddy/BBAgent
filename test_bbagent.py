#!/usr/bin/env python3
"""Minimal tests for bbagent.py — ToolRegistry, MemoryStore, memory_file_action, uninstall."""

import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

# ── Load bbagent.py by executing it in a controlled namespace ──────────────
_bbagent_path = Path(__file__).resolve().parent / "bbagent.py"
if not _bbagent_path.is_file():
    raise FileNotFoundError(f"bbagent.py not found at {_bbagent_path}")

_bbagent_ns = {"__file__": str(_bbagent_path.resolve()), "__name__": "__test__"}
exec(compile(_bbagent_path.read_text(encoding="utf-8"), str(_bbagent_path), "exec"), _bbagent_ns)

# Pull key symbols into test module scope
ToolRegistry = _bbagent_ns["ToolRegistry"]
MemoryStore = _bbagent_ns["MemoryStore"]
SessionSearch = _bbagent_ns["SessionSearch"]
_memory_file_action = _bbagent_ns["_memory_file_action"]
_read_memory_file = _bbagent_ns["_read_memory_file"]
_do_uninstall = _bbagent_ns["_do_uninstall"]
_tool_terminal = _bbagent_ns["_tool_terminal"]
_tool_search_files = _bbagent_ns["_tool_search_files"]
_tool_web_search = _bbagent_ns["_tool_web_search"]
_tool_session_search = _bbagent_ns["_tool_session_search"]
_ensure_session_search = _bbagent_ns["_ensure_session_search"]
AGENT_HOME = _bbagent_ns["AGENT_HOME"]


class TestToolRegistry(unittest.TestCase):
    """ToolRegistry: register, get_schemas, dispatch, get_tool_names."""

    def setUp(self):
        self.reg = ToolRegistry()
        self.reg.register("echo", "test", {
            "name": "echo", "description": "Echo input back",
            "parameters": {"type": "object", "properties": {"msg": {"type": "string"}}},
        }, lambda a, **kw: json.dumps({"echoed": a.get("msg", "")}))

    def test_register_and_get_names(self):
        self.assertIn("echo", self.reg.get_tool_names())

    def test_get_schemas_returns_openai_format(self):
        schemas = self.reg.get_schemas({"echo"})
        self.assertEqual(schemas[0]["type"], "function")
        self.assertEqual(schemas[0]["function"]["name"], "echo")

    def test_dispatch_calls_handler(self):
        self.assertEqual(json.loads(self.reg.dispatch("echo", {"msg": "hi"})), {"echoed": "hi"})

    def test_dispatch_unknown_tool(self):
        self.assertIn("error", json.loads(self.reg.dispatch("nope", {})))

    def test_check_fn_gates_tool(self):
        reg = ToolRegistry()
        reg.register("gated", "test", {"name": "gated"}, lambda a, **kw: "ok", check_fn=lambda: False)
        self.assertEqual(reg.get_schemas({"gated"}), [])

    def test_get_toolset_for(self):
        self.assertEqual(self.reg.get_toolset_for("echo"), "test")
        self.assertIsNone(self.reg.get_toolset_for("nope"))

    def test_handler_exception(self):
        reg = ToolRegistry()
        reg.register("crashy", "test", {"name": "crashy"},
                     lambda a, **kw: (_ for _ in ()).throw(RuntimeError("boom")))
        self.assertIn("boom", json.loads(reg.dispatch("crashy", {}))["error"])


class TestMemoryStore(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.store = MemoryStore(str(self.tmpdir / "mem.json"))

    def tearDown(self):
        shutil.rmtree(str(self.tmpdir), ignore_errors=True)

    def test_add_target(self):
        self.store.add_target("x.com", {"subdomains": ["admin"]})
        self.assertIn("x.com", self.store._data["targets"])

    def test_add_target_merges(self):
        self.store.add_target("x.com", {"a": 1})
        self.store.add_target("x.com", {"b": 2})
        self.assertIn("a", self.store._data["targets"]["x.com"])
        self.assertIn("b", self.store._data["targets"]["x.com"])

    def test_add_finding(self):
        self.store.add_finding({"type": "vuln", "target": "x.com", "summary": "XSS"})
        self.assertEqual(len(self.store._data["findings"]), 1)

    def test_add_learning(self):
        self.store.add_learning("nmap -sV is useful")
        self.assertEqual(len(self.store._data["learnings"]), 1)

    def test_get_context_empty(self):
        self.assertEqual(self.store.get_context(), "")

    def test_get_context_with_data(self):
        self.store.add_finding({"type": "vuln", "target": "x.com", "summary": "XSS found"})
        self.store.add_learning("technique learned")
        ctx = self.store.get_context()
        self.assertIn("XSS found", ctx)
        self.assertIn("technique learned", ctx)

    def test_persists_to_disk(self):
        self.store.add_learning("persistent fact")
        store2 = MemoryStore(str(self.tmpdir / "mem.json"))
        self.assertEqual(len(store2._data["learnings"]), 1)


class TestMemoryFileAction(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self._orig = _bbagent_ns["MEMORY_DIR"]
        _bbagent_ns["MEMORY_DIR"] = self.tmpdir

    def tearDown(self):
        _bbagent_ns["MEMORY_DIR"] = self._orig
        shutil.rmtree(str(self.tmpdir), ignore_errors=True)

    def test_add(self):
        r = _memory_file_action("add", "memory", "entry")
        self.assertTrue(r["success"])

    def test_list(self):
        _memory_file_action("add", "memory", "a")
        _memory_file_action("add", "memory", "b")
        self.assertEqual(_memory_file_action("list", "memory")["count"], 2)

    def test_get_alias(self):
        _memory_file_action("add", "memory", "x")
        self.assertEqual(_memory_file_action("get", "memory")["count"], 1)

    def test_duplicate_noop(self):
        _memory_file_action("add", "memory", "dup")
        self.assertIn("already", _memory_file_action("add", "memory", "dup")["message"])

    def test_replace(self):
        _memory_file_action("add", "memory", "old")
        self.assertTrue(_memory_file_action("replace", "memory", "new", old_text="old")["success"])

    def test_replace_no_match(self):
        _memory_file_action("add", "memory", "x")
        self.assertFalse(_memory_file_action("replace", "memory", "y", old_text="z")["success"])

    def test_replace_ambiguous(self):
        _memory_file_action("add", "memory", "foo A")
        _memory_file_action("add", "memory", "foo B")
        r = _memory_file_action("replace", "memory", "bar", old_text="foo")
        self.assertFalse(r["success"])
        self.assertIn("Multiple distinct", r["error"])

    def test_remove(self):
        _memory_file_action("add", "memory", "delete me")
        self.assertEqual(_memory_file_action("remove", "memory", old_text="delete")["entry_count"], 0)

    def test_remove_no_match(self):
        self.assertFalse(_memory_file_action("remove", "memory", old_text="nothing")["success"])

    def test_invalid_target(self):
        self.assertFalse(_memory_file_action("add", "invalid", "x")["success"])

    def test_unknown_action(self):
        self.assertFalse(_memory_file_action("fly", "memory")["success"])

    def test_char_limit(self):
        self.assertFalse(_memory_file_action("add", "memory", "x" * 3000)["success"])

    def test_user_target(self):
        self.assertTrue(_memory_file_action("add", "user", "prefs")["success"])

    def test_batch(self):
        r = _memory_file_action("add", "memory", operations=[
            {"action": "add", "content": "a"},
            {"action": "add", "content": "b"},
        ])
        self.assertTrue(r["success"])
        self.assertEqual(r["entry_count"], 2)


class TestUninstall(unittest.TestCase):
    """_do_uninstall: removes ~/.bbagent/ and script files."""

    def _call_uninstall(self, tmpdir):
        old_file = _bbagent_ns.get("__file__")
        _bbagent_ns["__file__"] = str(tmpdir / "bbagent.py")
        try:
            _do_uninstall()
        finally:
            _bbagent_ns["__file__"] = old_file

    @patch.object(Path, "home")
    def test_removes_dir_and_scripts(self, mock_home):
        tmpdir = Path(tempfile.mkdtemp())
        mock_home.return_value = tmpdir
        bbagent_dir = tmpdir / ".bbagent"
        bbagent_dir.mkdir(parents=True)
        (bbagent_dir / "config.yaml").write_text("test")
        for fname in ("bbagent.py", "setup_bbagent.py", "BBAGENT_BLUEPRINT.md"):
            (tmpdir / fname).write_text("dummy")
        self._call_uninstall(tmpdir)
        self.assertFalse(bbagent_dir.exists())
        for fname in ("bbagent.py", "setup_bbagent.py", "BBAGENT_BLUEPRINT.md"):
            self.assertFalse((tmpdir / fname).exists())

    @patch.object(Path, "home")
    def test_handles_missing_dir(self, mock_home):
        tmpdir = Path(tempfile.mkdtemp())
        mock_home.return_value = tmpdir
        self._call_uninstall(tmpdir)

    @patch.object(Path, "home")
    @patch("shutil.rmtree")
    def test_rmtree_called(self, mock_rmtree, mock_home):
        tmpdir = Path(tempfile.mkdtemp())
        mock_home.return_value = tmpdir
        (tmpdir / ".bbagent").mkdir(parents=True)
        self._call_uninstall(tmpdir)
        mock_rmtree.assert_called_once()


class TestBuiltinTools(unittest.TestCase):
    def test_terminal_missing_command(self):
        self.assertIn("error", json.loads(_tool_terminal({"command": ""})))

    def test_search_files_no_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = json.loads(_tool_search_files({"pattern": "*.nonexistent", "path": tmp}))
            self.assertEqual(r["count"], 0)

    def test_web_search_missing_query(self):
        self.assertIn("error", json.loads(_tool_web_search({"query": ""})))


class TestSessionSearch(unittest.TestCase):
    """SessionSearch: FTS5 search, LIKE fallback, existing session indexing."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.db_path = str(self.tmpdir / "state.db")
        self.ss = SessionSearch(self.db_path)

    def tearDown(self):
        self.ss.close()
        shutil.rmtree(str(self.tmpdir), ignore_errors=True)

    def _sample_messages(self):
        return [
            {"role": "user", "content": "Scan target x.com for open ports"},
            {"role": "assistant", "content": "Running nmap scan...",
             "tool_calls": [{"function": {"name": "terminal"}}]},
            {"role": "tool", "content": '{"output": "22/tcp open, 80/tcp open"}'},
            {"role": "assistant", "content": "Found open ports 22 and 80 on x.com"},
        ]

    # ── FTS5 path (primary) ────────────────────────────────────────────────

    def test_fts_search_finds_content(self):
        self.ss.index_session("sess1", "gpt-4o", self._sample_messages())
        results = self.ss.search("nmap")
        self.assertTrue(any("nmap" in r["snippet"] for r in results))

    def test_fts_search_returns_session_id_and_model(self):
        self.ss.index_session("sess1", "gpt-4o", self._sample_messages())
        results = self.ss.search("nmap")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["session_id"], "sess1")
        self.assertEqual(results[0]["model"], "gpt-4o")

    def test_fts_search_multi_session(self):
        self.ss.index_session("s1", "gpt-4o", self._sample_messages())
        self.ss.index_session("s2", "claude", [
            {"role": "user", "content": "Analyze api.x.com endpoints"},
        ])
        results = self.ss.search("nmap")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["session_id"], "s1")
        results = self.ss.search("api.x.com")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["session_id"], "s2")

    def test_fts_search_no_match_returns_empty(self):
        self.ss.index_session("s1", "gpt-4o", self._sample_messages())
        results = self.ss.search("zzzznotfound")
        self.assertEqual(len(results), 0)

    def test_fts_search_empty_query(self):
        self.ss.index_session("s1", "gpt-4o", self._sample_messages())
        results = self.ss.search("")
        self.assertEqual(len(results), 0)

    def test_fts_search_max_results(self):
        self.ss.index_session("s1", "gpt-4o", self._sample_messages())
        self.ss.index_session("s2", "gpt-4o", [
            {"role": "user", "content": "nmap scan target y.com"},
        ])
        results = self.ss.search("nmap", max_results=1)
        self.assertLessEqual(len(results), 1)

    def test_fts_reindex_replaces_old_messages(self):
        self.ss.index_session("s1", "gpt-4o", [
            {"role": "user", "content": "old content"},
        ])
        self.ss.index_session("s1", "gpt-4o", [
            {"role": "user", "content": "new content"},
        ])
        results = self.ss.search("new")
        self.assertEqual(len(results), 1)
        results = self.ss.search("old")
        self.assertEqual(len(results), 0)

    # ── LIKE fallback path (when FTS5 unavailable) ───────────────────────────

    def test_like_fallback_finds_content(self):
        self.ss._fts_ok = False
        self.ss.index_session("s1", "gpt-4o", self._sample_messages())
        results = self.ss.search("nmap")
        self.assertTrue(any("nmap" in r["snippet"] for r in results))

    def test_like_fallback_no_match(self):
        self.ss._fts_ok = False
        self.ss.index_session("s1", "gpt-4o", self._sample_messages())
        results = self.ss.search("nonexistent")
        self.assertEqual(len(results), 0)

    def test_like_fallback_empty_query(self):
        self.ss._fts_ok = False
        self.ss.index_session("s1", "gpt-4o", self._sample_messages())
        results = self.ss.search("")
        # LIKE '%%' matches all non-null content; empty query should not happen in practice
        self.assertIn("s1", [r["session_id"] for r in results])

    # ── Existing session indexing ────────────────────────────────────────────

    def test_index_existing_sessions(self):
        sessions_dir = self.tmpdir / ".bbagent" / "sessions"
        sessions_dir.mkdir(parents=True, exist_ok=True)
        (sessions_dir / "old_sess.json").write_text(json.dumps({
            "session_id": "old_sess",
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": "legacy recon data"}],
        }))
        # Patch AGENT_HOME to point at tmpdir so _index_existing_sessions
        # looks in the right place; also reset _init_sessions guard.
        old_home = _bbagent_ns["AGENT_HOME"]
        _bbagent_ns["AGENT_HOME"] = self.tmpdir / ".bbagent"
        self.ss._init_sessions = False
        self.ss._index_existing_sessions()
        _bbagent_ns["AGENT_HOME"] = old_home

        results = self.ss.search("legacy recon")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["session_id"], "old_sess")

    def test_index_existing_sessions_skips_bad_json(self):
        sessions_dir = self.tmpdir / ".bbagent" / "sessions"
        sessions_dir.mkdir(parents=True, exist_ok=True)
        (sessions_dir / "good.json").write_text(json.dumps({
            "session_id": "g",
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": "good data"}],
        }))
        (sessions_dir / "bad.json").write_text("not json at all")
        (sessions_dir / "empty.json").write_text("")

        old_home = _bbagent_ns["AGENT_HOME"]
        _bbagent_ns["AGENT_HOME"] = self.tmpdir / ".bbagent"
        self.ss._init_sessions = False
        self.ss._index_existing_sessions()
        _bbagent_ns["AGENT_HOME"] = old_home

        results = self.ss.search("good data")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["session_id"], "g")

    def test_index_existing_sessions_no_dir(self):
        # No sessions directory — should not raise
        old_home = _bbagent_ns["AGENT_HOME"]
        _bbagent_ns["AGENT_HOME"] = self.tmpdir / ".bbagent"
        self.ss._init_sessions = False
        self.ss._index_existing_sessions()
        _bbagent_ns["AGENT_HOME"] = old_home
        # No assertion needed — just ensure no exception

    def test_index_existing_sessions_runs_once(self):
        sessions_dir = self.tmpdir / ".bbagent" / "sessions"
        sessions_dir.mkdir(parents=True, exist_ok=True)
        (sessions_dir / "s1.json").write_text(json.dumps({
            "session_id": "s1", "model": "x",
            "messages": [{"role": "user", "content": "first run"}],
        }))
        old_home = _bbagent_ns["AGENT_HOME"]
        _bbagent_ns["AGENT_HOME"] = self.tmpdir / ".bbagent"
        self.ss._init_sessions = False
        self.ss._index_existing_sessions()
        # Second session added after first index
        (sessions_dir / "s2.json").write_text(json.dumps({
            "session_id": "s2", "model": "x",
            "messages": [{"role": "user", "content": "second run"}],
        }))
        self.ss._index_existing_sessions()  # should be no-op due to _init_sessions guard
        _bbagent_ns["AGENT_HOME"] = old_home

        results = self.ss.search("second run")
        self.assertEqual(len(results), 0, "Guard should prevent double index")

    # ── Edge cases ───────────────────────────────────────────────────────────

    def test_search_with_no_connection(self):
        ss = SessionSearch(str(self.tmpdir / "no_conn.db"))
        ss.close()
        results = ss.search("anything")
        self.assertEqual(results, [])

    def test_index_session_no_connection(self):
        ss = SessionSearch(str(self.tmpdir / "no_conn2.db"))
        ss.close()
        ss.index_session("x", "m", self._sample_messages())
        # Should not raise

    def test_session_search_tool_missing_query(self):
        r = json.loads(_tool_session_search({}))
        self.assertIn("error", r)

    def test_session_search_tool_no_results(self):
        r = json.loads(_tool_session_search({"query": "zzzznothing"}))
        self.assertEqual(r["results"], [])


class TestSessionPruning(unittest.TestCase):
    """SessionSearch.prune_older_than: auto-pruning old sessions from DB + JSON files."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.db_path = str(self.tmpdir / "state.db")
        self.ss = SessionSearch(self.db_path, prune_days=90)

    def tearDown(self):
        self.ss.close()
        shutil.rmtree(str(self.tmpdir), ignore_errors=True)

    def _index_with_age(self, session_id: str, content: str, age_days: float):
        """Index a session and then manually adjust its started_at to simulate age."""
        self.ss.index_session(session_id, "gpt-4o", [
            {"role": "user", "content": content},
        ])
        # Rewrite timestamp to simulate age
        cutoff = time.time() - age_days * 86400
        self.ss._conn.execute(
            "UPDATE sessions SET started_at = ? WHERE id = ?", (cutoff, session_id)
        )
        self.ss._conn.commit()

    def _ids_in_db(self):
        return {r["id"] for r in
                self.ss._conn.execute("SELECT id FROM sessions").fetchall()}

    # ── SQLite pruning ───────────────────────────────────────────────────

    def test_prune_older_deletes_sessions(self):
        self._index_with_age("old_sess", "old data", 100)  # 100 days old
        self._index_with_age("new_sess", "new data", 10)   # 10 days old
        self.ss.prune_older_than(90)
        ids = self._ids_in_db()
        self.assertIn("new_sess", ids)
        self.assertNotIn("old_sess", ids)

    def test_prune_older_keeps_recent_sessions(self):
        self._index_with_age("recent", "recent data", 30)
        self.ss.prune_older_than(90)
        self.assertIn("recent", self._ids_in_db())

    def test_prune_older_keeps_exactly_at_boundary(self):
        self._index_with_age("boundary", "boundary data", 89.9)
        self.ss.prune_older_than(90)
        # 89.9 days < 90 days, boundary session is kept
        self.assertIn("boundary", self._ids_in_db())

    def test_prune_older_removes_fts_entries(self):
        self._index_with_age("old_sess", "prune me", 100)
        self.ss.prune_older_than(90)
        results = self.ss.search("prune")
        self.assertEqual(len(results), 0)

    def test_prune_older_no_old_sessions(self):
        self._index_with_age("fresh", "fresh data", 1)
        self.ss.prune_older_than(90)
        self.assertEqual(len(self._ids_in_db()), 1)

    def test_prune_older_empty_db(self):
        self.ss.prune_older_than(90)
        self.assertEqual(len(self._ids_in_db()), 0)

    # ── JSON file cleanup ─────────────────────────────────────────────────

    def test_prune_older_removes_json_files(self):
        sessions_dir = self.tmpdir / ".bbagent" / "sessions"
        sessions_dir.mkdir(parents=True, exist_ok=True)
        # Write JSON files that match session IDs
        old_id = "old_sess"
        new_id = "new_sess"
        (sessions_dir / f"{old_id}.json").write_text(json.dumps({
            "session_id": old_id, "model": "gpt-4o",
            "messages": [{"role": "user", "content": "old data"}],
        }))
        (sessions_dir / f"{new_id}.json").write_text(json.dumps({
            "session_id": new_id, "model": "gpt-4o",
            "messages": [{"role": "user", "content": "new data"}],
        }))

        old_home = _bbagent_ns["AGENT_HOME"]
        _bbagent_ns["AGENT_HOME"] = self.tmpdir / ".bbagent"

        self._index_with_age(old_id, "old data", 100)
        self._index_with_age(new_id, "new data", 10)
        self.ss.prune_older_than(90)

        _bbagent_ns["AGENT_HOME"] = old_home

        self.assertFalse((sessions_dir / f"{old_id}.json").exists())
        self.assertTrue((sessions_dir / f"{new_id}.json").exists())

    # ── Periodic pruning in index_session ─────────────────────────────────

    def test_periodic_prune_triggers_every_10(self):
        with patch.object(SessionSearch, "prune_older_than") as mock_prune:
            for i in range(9):
                self.ss.index_session(f"s{i}", "m", [{"role": "user", "content": f"d{i}"}])
            mock_prune.assert_not_called()
            self.ss.index_session("s9", "m", [{"role": "user", "content": "d9"}])
            mock_prune.assert_called_once()

    def test_prune_older_fts_fallback(self):
        self.ss._fts_ok = False
        self._index_with_age("old_sess", "fallback test", 100)
        self.ss.prune_older_than(90)
        results = self.ss.search("fallback")
        self.assertEqual(len(results), 0)


class TestStatsCommand(unittest.TestCase):
    """BBAgent._cmd_stats: /stats slash command handler."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self._orig_ensure = _bbagent_ns.get("_ensure_session_search")
        self._orig_print = _bbagent_ns.get("_safe_print")
        self._printed = []
        _bbagent_ns["_safe_print"] = lambda *a, **kw: self._printed.append(" ".join(str(x) for x in a))

    def tearDown(self):
        _bbagent_ns["_ensure_session_search"] = self._orig_ensure
        _bbagent_ns["_safe_print"] = self._orig_print
        shutil.rmtree(str(self.tmpdir), ignore_errors=True)

    def _stats(self):
        BBAgent = _bbagent_ns["BBAgent"]
        BBAgent._cmd_stats()

    def test_shows_zero_when_empty(self):
        ss = SessionSearch(str(self.tmpdir / "state.db"))
        _bbagent_ns["_ensure_session_search"] = lambda: ss
        self._stats()
        combined = "\n".join(self._printed)
        self.assertIn("0", combined)
        self.assertIn("bytes", combined)
        ss.close()

    def test_shows_session_count(self):
        ss = SessionSearch(str(self.tmpdir / "state.db"))
        ss.index_session("s1", "gpt-4o", [{"role": "user", "content": "hello"}])
        ss.index_session("s2", "gpt-4o", [{"role": "user", "content": "world"}])
        _bbagent_ns["_ensure_session_search"] = lambda: ss
        self._stats()
        combined = "\n".join(self._printed)
        self.assertIn("2", combined)
        self.assertIn("Sessions indexed", combined)
        ss.close()

    def test_shows_timestamps(self):
        ss = SessionSearch(str(self.tmpdir / "state.db"))
        ss.index_session("s1", "gpt-4o", [{"role": "user", "content": "hello"}])
        _bbagent_ns["_ensure_session_search"] = lambda: ss
        self._stats()
        combined = "\n".join(self._printed)
        self.assertIn("Oldest session", combined)
        self.assertIn("Newest session", combined)
        ss.close()


class TestRetentionFlag(unittest.TestCase):
    """main(): --retention flag writes config.yaml correctly."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self._orig_argv = sys.argv
        self._orig_home = _bbagent_ns["AGENT_HOME"]

    def tearDown(self):
        sys.argv = self._orig_argv
        _bbagent_ns["AGENT_HOME"] = self._orig_home
        shutil.rmtree(str(self.tmpdir), ignore_errors=True)

    def _run_main(self, args: list):
        sys.argv = ["bbagent.py"] + args
        _bbagent_ns["AGENT_HOME"] = self.tmpdir / ".bbagent"
        main = _bbagent_ns["main"]
        main()

    def test_writes_correct_value(self):
        self._run_main(["--retention", "60"])
        cfg_path = self.tmpdir / ".bbagent" / "config.yaml"
        self.assertTrue(cfg_path.exists())
        import yaml
        cfg = yaml.safe_load(cfg_path.read_text())
        self.assertEqual(cfg["session_search"]["prune_days"], 60)

    def test_creates_config_if_missing(self):
        cfg_path = self.tmpdir / ".bbagent" / "config.yaml"
        self.assertFalse(cfg_path.exists())
        self._run_main(["--retention", "30"])
        self.assertTrue(cfg_path.exists())

    def test_preserves_existing_keys(self):
        cfg_path = self.tmpdir / ".bbagent" / "config.yaml"
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        cfg_path.write_text("model: gpt-4o\nmax_iterations: 50\n")
        self._run_main(["--retention", "45"])
        import yaml
        cfg = yaml.safe_load(cfg_path.read_text())
        self.assertEqual(cfg["model"], "gpt-4o")
        self.assertEqual(cfg["session_search"]["prune_days"], 45)

    def test_overwrites_existing_prune_days(self):
        cfg_path = self.tmpdir / ".bbagent" / "config.yaml"
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        import yaml
        cfg_path.write_text(yaml.dump({"session_search": {"prune_days": 90}}))
        self._run_main(["--retention", "120"])
        cfg = yaml.safe_load(cfg_path.read_text())
        self.assertEqual(cfg["session_search"]["prune_days"], 120)

    def test_ignores_zero_retention(self):
        self._run_main(["--retention", "0"])
        cfg_path = self.tmpdir / ".bbagent" / "config.yaml"
        self.assertFalse(cfg_path.exists())


class TestSearchCommand(unittest.TestCase):
    """BBAgent._cmd_search: /search slash command handler."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self._orig_ensure = _bbagent_ns.get("_ensure_session_search")
        self._orig_print = _bbagent_ns.get("_safe_print")
        self._printed = []
        _bbagent_ns["_safe_print"] = lambda *a, **kw: self._printed.append(" ".join(str(x) for x in a))

    def tearDown(self):
        _bbagent_ns["_ensure_session_search"] = self._orig_ensure
        _bbagent_ns["_safe_print"] = self._orig_print
        shutil.rmtree(str(self.tmpdir), ignore_errors=True)

    def _search(self, query):
        BBAgent = _bbagent_ns["BBAgent"]
        BBAgent._cmd_search(query)

    def test_empty_query_shows_usage(self):
        self._search("")
        self.assertTrue(any("Usage:" in l for l in self._printed))

    def test_no_results_shows_message(self):
        ss = SessionSearch(str(self.tmpdir / "state.db"))
        _bbagent_ns["_ensure_session_search"] = lambda: ss
        self._search("nonexistent")
        self.assertTrue(any("No matching" in l for l in self._printed))
        ss.close()

    def test_shows_results(self):
        ss = SessionSearch(str(self.tmpdir / "state.db"))
        ss.index_session("sess1", "gpt-4o", [
            {"role": "user", "content": "recon data for x.com"},
        ])
        _bbagent_ns["_ensure_session_search"] = lambda: ss
        self._search("x.com")
        combined = "\n".join(self._printed)
        self.assertIn("sess1", combined)
        self.assertIn("recon", combined)
        ss.close()

    def test_shows_multiple_results(self):
        ss = SessionSearch(str(self.tmpdir / "state.db"))
        ss.index_session("s1", "gpt-4o", [{"role": "user", "content": "nmap on x.com"}])
        ss.index_session("s2", "claude", [{"role": "user", "content": "nmap on y.com"}])
        _bbagent_ns["_ensure_session_search"] = lambda: ss
        self._search("nmap")
        combined = "\n".join(self._printed)
        self.assertIn("2 session", combined)
        self.assertIn("s1", combined)
        self.assertIn("s2", combined)
        ss.close()


class TestPruneCommand(unittest.TestCase):
    """BBAgent._cmd_prune: /prune slash command handler."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self._orig_ensure = _bbagent_ns.get("_ensure_session_search")
        self._orig_load = _bbagent_ns.get("_load_session_search_config")
        self._orig_print = _bbagent_ns.get("_safe_print")
        self._printed = []
        _bbagent_ns["_safe_print"] = lambda *a, **kw: self._printed.append(" ".join(str(x) for x in a))

    def tearDown(self):
        _bbagent_ns["_ensure_session_search"] = self._orig_ensure
        _bbagent_ns["_load_session_search_config"] = self._orig_load
        _bbagent_ns["_safe_print"] = self._orig_print
        shutil.rmtree(str(self.tmpdir), ignore_errors=True)

    def _prune(self):
        BBAgent = _bbagent_ns["BBAgent"]
        BBAgent._cmd_prune()

    def test_prune_empty_db(self):
        ss = SessionSearch(str(self.tmpdir / "state.db"))
        _bbagent_ns["_ensure_session_search"] = lambda: ss
        _bbagent_ns["_load_session_search_config"] = lambda: {"prune_days": 90}
        self._prune()
        combined = "\n".join(self._printed)
        self.assertIn("0", combined)
        self.assertIn("Retention: 90 days", combined)
        ss.close()

    def test_prune_removes_old_sessions(self):
        ss = SessionSearch(str(self.tmpdir / "state.db"), prune_days=90)
        # Index an old session and manually set its age
        ss.index_session("old_sess", "gpt-4o", [{"role": "user", "content": "old data"}])
        ss._conn.execute("UPDATE sessions SET started_at = ? WHERE id = ?",
                         (time.time() - 100 * 86400, "old_sess"))
        ss._conn.commit()
        # Index a recent session
        ss.index_session("new_sess", "gpt-4o", [{"role": "user", "content": "new data"}])

        _bbagent_ns["_ensure_session_search"] = lambda: ss
        _bbagent_ns["_load_session_search_config"] = lambda: {"prune_days": 90}
        self._prune()
        combined = "\n".join(self._printed)
        self.assertIn("Removed:         1", combined)
        ss.close()

    def test_prune_shows_before_and_after(self):
        ss = SessionSearch(str(self.tmpdir / "state.db"), prune_days=90)
        ss.index_session("s1", "gpt-4o", [{"role": "user", "content": "data"}])
        ss.index_session("s2", "gpt-4o", [{"role": "user", "content": "data"}])

        _bbagent_ns["_ensure_session_search"] = lambda: ss
        _bbagent_ns["_load_session_search_config"] = lambda: {"prune_days": 90}
        self._prune()
        combined = "\n".join(self._printed)
        self.assertIn("Sessions before: 2", combined)
        self.assertIn("Sessions after:  2", combined)
        ss.close()


class TestHelpClearCommand(unittest.TestCase):
    """BBAgent._cmd_help and _cmd_clear: /help and /clear slash commands."""

    def setUp(self):
        self._orig_print = _bbagent_ns.get("_safe_print")
        self._printed = []
        self._system_calls = []
        _bbagent_ns["_safe_print"] = lambda *a, **kw: self._printed.append(" ".join(str(x) for x in a))
        # Patch os.system on the os module imported by bbagent.py
        self._system_patcher = patch.object(_bbagent_ns["os"], "system",
                                            lambda c: self._system_calls.append(c))
        self._system_patcher.start()

    def tearDown(self):
        _bbagent_ns["_safe_print"] = self._orig_print
        self._system_patcher.stop()

    def _help(self):
        BBAgent = _bbagent_ns["BBAgent"]
        BBAgent._cmd_help()

    def _clear(self):
        BBAgent = _bbagent_ns["BBAgent"]
        BBAgent._cmd_clear()

    def test_help_lists_all_commands(self):
        self._help()
        combined = "\n".join(self._printed)
        self.assertIn("/search", combined)
        self.assertIn("/stats", combined)
        self.assertIn("/prune", combined)
        self.assertIn("/help", combined)
        self.assertIn("/clear", combined)
        self.assertIn("/exit", combined)
        self.assertIn("Available Commands", combined)

    def test_clear_calls_os_system(self):
        self._clear()
        self.assertEqual(len(self._system_calls), 1)
        import os as real_os
        expected = "cls" if real_os.name == "nt" else "clear"
        self.assertEqual(self._system_calls[0], expected)

    def test_clear_does_not_print(self):
        self._clear()
        self.assertEqual(len(self._printed), 0)


if __name__ == "__main__":
    unittest.main()
