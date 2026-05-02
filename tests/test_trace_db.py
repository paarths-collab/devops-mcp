"""
Tests for core/trace_db.py — persistent SQLite trace logger.

All tests use an isolated in-memory database so they never touch
the production data/traces.db file.
"""

import json
import pytest
from observable_agent_panel.core.trace_db import TraceDB


@pytest.fixture
def db():
    """Fresh in-memory TraceDB for every test."""
    return TraceDB(db_path=":memory:")


# ─── Schema & initialization ──────────────────────────────────────────────────

def test_db_initializes_clean(db):
    """TraceDB starts with zero traces."""
    assert db.get_recent_traces(100) == []


def test_schema_columns_exist(db):
    """The traces table has the required observability columns."""
    cursor = db.conn.execute("PRAGMA table_info(traces)")
    columns = {row[1] for row in cursor.fetchall()}
    required = {
        "run_id", "timestamp", "query", "similarity_score",
        "routing_decision", "hops", "final_answer", "outcome",
        "memory_facts_used", "explanation", "hop_limit_hit",
    }
    assert required.issubset(columns)


# ─── Write path ───────────────────────────────────────────────────────────────

def test_start_trace_creates_row(db):
    run_id = db.start_trace("Why is my pod crashing?")
    assert run_id is not None
    traces = db.get_recent_traces(10)
    assert len(traces) == 1
    assert traces[0]["query"] == "Why is my pod crashing?"
    assert traces[0]["run_id"] == run_id


def test_start_trace_returns_unique_ids(db):
    id1 = db.start_trace("query one")
    id2 = db.start_trace("query two")
    assert id1 != id2


def test_update_triage_persists(db):
    db.start_trace("test query")
    db.update_triage(score=0.91, decision="memory_only")
    trace = db.get_recent_traces(1)[0]
    assert abs(trace["similarity_score"] - 0.91) < 1e-6
    assert trace["routing_decision"] == "memory_only"


def test_log_hop_appends_to_array(db):
    db.start_trace("test")
    db.log_hop("search_github_prs", {"query": "auth bug"}, "success", latency_ms=120.5)
    db.log_hop("search_stackexchange", {"query": "auth"}, "error", latency_ms=45.0)
    trace = db.get_recent_traces(1)[0]
    hops = trace["hops"]
    assert len(hops) == 2
    assert hops[0]["tool"] == "search_github_prs"
    assert hops[0]["status"] == "success"
    assert abs(hops[0]["latency_ms"] - 120.5) < 1e-3
    assert hops[1]["tool"] == "search_stackexchange"
    assert hops[1]["status"] == "error"


def test_log_hop_empty_when_no_active_run(db):
    """Calling log_hop without start_trace is a no-op, not a crash."""
    db.log_hop("some_tool", {}, "success")  # should not raise


def test_set_memory_facts_persists(db):
    db.start_trace("test")
    db.set_memory_facts(["fact A", "fact B"])
    trace = db.get_recent_traces(1)[0]
    assert trace["memory_facts_used"] == ["fact A", "fact B"]


def test_finalize_trace_normal(db):
    db.start_trace("query")
    db.finalize_trace("The answer is X.", hop_limit_hit=False, explanation="Went to memory.")
    trace = db.get_recent_traces(1)[0]
    assert trace["final_answer"] == "The answer is X."
    assert trace["hop_limit_hit"] == 0
    assert trace["explanation"] == "Went to memory."


def test_finalize_trace_hop_limit_hit(db):
    db.start_trace("hard query")
    db.finalize_trace("System Error: Reached limit.", hop_limit_hit=True)
    trace = db.get_recent_traces(1)[0]
    assert trace["hop_limit_hit"] == 1


def test_set_outcome_y(db):
    db.start_trace("query")
    db.set_outcome("y")
    trace = db.get_recent_traces(1)[0]
    assert trace["outcome"] == "y"


def test_set_outcome_n(db):
    db.start_trace("query")
    db.set_outcome("n")
    trace = db.get_recent_traces(1)[0]
    assert trace["outcome"] == "n"


# ─── Read path ────────────────────────────────────────────────────────────────

def test_get_recent_traces_respects_limit(db):
    for i in range(10):
        db.start_trace(f"query {i}")
        db.finalize_trace(f"answer {i}")
    traces = db.get_recent_traces(5)
    assert len(traces) == 5


def test_get_recent_traces_order_newest_first(db):
    db.start_trace("first")
    db.finalize_trace("a1")
    db.start_trace("second")
    db.finalize_trace("a2")
    traces = db.get_recent_traces(2)
    # Most recent should come first
    assert traces[0]["query"] == "second"
    assert traces[1]["query"] == "first"


def test_get_trace_by_id(db):
    run_id = db.start_trace("specific query")
    db.finalize_trace("specific answer")
    result = db.get_trace(run_id)
    assert result is not None
    assert result["run_id"] == run_id
    assert result["query"] == "specific query"


def test_get_trace_missing_id_returns_none(db):
    result = db.get_trace("nonexistent-uuid")
    assert result is None


def test_hops_decoded_as_list(db):
    """hops column is returned as a Python list, not a JSON string."""
    db.start_trace("q")
    trace = db.get_recent_traces(1)[0]
    assert isinstance(trace["hops"], list)


def test_memory_facts_decoded_as_list(db):
    db.start_trace("q")
    db.set_memory_facts(["x", "y"])
    trace = db.get_recent_traces(1)[0]
    assert isinstance(trace["memory_facts_used"], list)


# ─── Full lifecycle ───────────────────────────────────────────────────────────

def test_complete_run_lifecycle(db):
    """End-to-end: start → triage → hops → feedback → finalize."""
    run_id = db.start_trace("How do I fix CORS in FastAPI?")
    db.update_triage(0.72, "hybrid")
    db.set_memory_facts(["CORS middleware PR #1234"])
    db.log_hop("search_github_prs", {"query": "CORS"}, "success", 88.0)
    db.finalize_trace("Add CORSMiddleware to app.", hop_limit_hit=False, explanation="Hybrid path.")
    db.set_outcome("y")

    t = db.get_trace(run_id)
    assert t["routing_decision"] == "hybrid"
    assert len(t["hops"]) == 1
    assert t["outcome"] == "y"
    assert t["hop_limit_hit"] == 0
    assert "CORSMiddleware" in t["final_answer"]
