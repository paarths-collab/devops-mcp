"""
Integration tests for the observability layer wired into the Orchestrator.

The LLM and GitHub API are mocked so these tests run fully offline.
They verify that every code path (memory-only, hybrid, tools, hop-limit)
correctly writes a structured trace to SQLite.
"""

import json
import pytest
from unittest.mock import MagicMock, patch

from devops_agent.core.orchestrator import Orchestrator, HIGH_CONFIDENCE, HYBRID_THRESHOLD
from observable_agent_panel.core.trace_db import TraceDB
from devops_agent.core.llm_client import LLMClient
from devops_agent.memory.long_term import LongTermMemory


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def isolated_db(tmp_path):
    """An isolated TraceDB backed by a temp file (not :memory: so we can inspect it)."""
    db = TraceDB(db_path=str(tmp_path / "test_traces.db"))
    return db


@pytest.fixture
def mock_llm():
    llm = MagicMock(spec=LLMClient)
    llm.simple_chat.return_value = "Mocked LLM answer."
    # Minimal valid tool-response: no tool_calls → stop immediately
    llm.chat.return_value = {
        "choices": [{"message": {"content": "Mocked tool answer.", "tool_calls": None}}]
    }
    return llm


@pytest.fixture
def orchestrator(mock_llm, isolated_db):
    memory = LongTermMemory(db_path=":memory:")
    orch = Orchestrator(llm_client=mock_llm, long_term=memory)
    # Patch global singleton so orchestrator writes to our isolated db
    with patch("devops_agent.core.orchestrator.trace_db", isolated_db):
        yield orch, isolated_db


# ─── Memory-only path ─────────────────────────────────────────────────────────

def test_memory_path_creates_trace(orchestrator):
    orch, db = orchestrator
    query = "How do I fix CORS in FastAPI?"

    # Plant a high-confidence match in memory
    high_score_match = {
        "score": HIGH_CONFIDENCE + 0.05,
        "issue": "CORS issue",
        "fix": "Add CORSMiddleware",
        "context": "...",
        "repo_name": "test/repo",
        "tags": [],
    }
    orch.memory.search_memory = MagicMock(return_value=[high_score_match])
    orch.temp_memory.search_memory = MagicMock(return_value=[])

    orch.process_query(query)

    traces = db.get_recent_traces(1)
    assert len(traces) == 1
    t = traces[0]
    assert t["query"] == query
    assert t["routing_decision"] == "memory_only"
    assert t["similarity_score"] >= HIGH_CONFIDENCE
    assert t["final_answer"] == "Mocked LLM answer."
    assert t["hop_limit_hit"] == 0
    assert t["explanation"] is not None


def test_memory_path_records_facts_used(orchestrator):
    orch, db = orchestrator
    high_score_match = {
        "score": HIGH_CONFIDENCE + 0.05,
        "issue": "JWT auth bug",
        "fix": "Check scope",
        "context": "",
        "repo_name": "test/repo",
        "tags": [],
    }
    orch.memory.search_memory = MagicMock(return_value=[high_score_match])
    orch.temp_memory.search_memory = MagicMock(return_value=[])

    orch.process_query("auth issue")

    t = db.get_recent_traces(1)[0]
    assert "JWT auth bug" in t["memory_facts_used"]


# ─── Tools-first path ─────────────────────────────────────────────────────────

def test_tools_path_creates_trace(orchestrator):
    orch, db = orchestrator
    orch.memory.search_memory = MagicMock(return_value=[])
    orch.temp_memory.search_memory = MagicMock(return_value=[])

    orch.process_query("What is a totally unknown error?")

    traces = db.get_recent_traces(1)
    assert len(traces) == 1
    t = traces[0]
    assert t["routing_decision"] == "tools_only"
    assert t["final_answer"] == "Mocked tool answer."
    assert t["hop_limit_hit"] == 0


def test_tools_path_records_hop(orchestrator):
    orch, db = orchestrator

    # First LLM call returns a tool_call, second call returns a final answer
    tool_call_response = {
        "choices": [{
            "message": {
                "content": "",
                "tool_calls": [{
                    "id": "tc-1",
                    "function": {
                        "name": "search_github_prs",
                        "arguments": json.dumps({"query": "bug", "repo": "test/repo"}),
                    },
                }],
            }
        }]
    }
    final_response = {
        "choices": [{"message": {"content": "Fixed it.", "tool_calls": None}}]
    }
    orch.llm.chat.side_effect = [tool_call_response, final_response]
    orch.memory.search_memory = MagicMock(return_value=[])
    orch.temp_memory.search_memory = MagicMock(return_value=[])

    with patch("devops_agent.core.orchestrator.execute_tool", return_value={"status": "success", "results": []}):
        orch.process_query("find a bug")

    t = db.get_recent_traces(1)[0]
    assert len(t["hops"]) == 1
    assert t["hops"][0]["tool"] == "search_github_prs"
    assert t["hops"][0]["status"] == "success"
    assert t["hops"][0]["latency_ms"] is not None


# ─── Hop-limit exhaustion path ────────────────────────────────────────────────

def test_hop_limit_records_flag(orchestrator):
    orch, db = orchestrator

    # Every LLM call returns a tool_call, forcing the loop to run until MAX_TOOL_HOPS
    tool_call_response = {
        "choices": [{
            "message": {
                "content": "",
                "tool_calls": [{
                    "id": "tc-1",
                    "function": {
                        "name": "search_github_prs",
                        "arguments": json.dumps({"query": "x", "repo": "a/b"}),
                    },
                }],
            }
        }]
    }
    orch.llm.chat.return_value = tool_call_response
    orch.memory.search_memory = MagicMock(return_value=[])
    orch.temp_memory.search_memory = MagicMock(return_value=[])

    with patch("devops_agent.core.orchestrator.execute_tool", return_value={"status": "success"}):
        result = orch.process_query("impossible query")

    t = db.get_recent_traces(1)[0]
    assert t["hop_limit_hit"] == 1
    assert "System Error" in t["final_answer"]


# ─── Multiple sequential runs ─────────────────────────────────────────────────

def test_multiple_runs_each_get_unique_trace(orchestrator):
    orch, db = orchestrator
    orch.memory.search_memory = MagicMock(return_value=[])
    orch.temp_memory.search_memory = MagicMock(return_value=[])

    orch.process_query("query one")
    orch.process_query("query two")
    orch.process_query("query three")

    traces = db.get_recent_traces(10)
    assert len(traces) == 3
    run_ids = {t["run_id"] for t in traces}
    assert len(run_ids) == 3  # all unique


# ─── Outcome labeling (Feature 3) ────────────────────────────────────────────

def test_outcome_can_be_set_after_run(orchestrator):
    orch, db = orchestrator
    orch.memory.search_memory = MagicMock(return_value=[])
    orch.temp_memory.search_memory = MagicMock(return_value=[])

    orch.process_query("any query")
    db.set_outcome("n")

    t = db.get_recent_traces(1)[0]
    assert t["outcome"] == "n"
