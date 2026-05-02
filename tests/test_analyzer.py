"""
Tests for core/analyzer.py — failure analysis, anomaly alerts, trace diff.

All tests use synthetic trace dicts so no real DB or LLM is required.
"""

import io
import pytest
from unittest.mock import patch
from rich.console import Console

from observable_agent_panel.core.analyzer import (
    print_failure_report,
    print_trace_diff,
    print_anomaly_alerts,
    ALERT_TOOL_FAIL_RATE,
    ALERT_LOW_SIMILARITY,
    ALERT_HOP_LIMIT_RATE,
    RECENT_WINDOW,
    _tool_stats,
)


# ─── Fixtures ─────────────────────────────────────────────────────────────────

def _trace(
    run_id="abc",
    query="test query",
    routing="tools_only",
    score=0.5,
    hops=None,
    outcome=None,
    hop_limit_hit=False,
):
    return {
        "run_id": run_id,
        "timestamp": "2026-05-01T10:00:00",
        "query": query,
        "similarity_score": score,
        "routing_decision": routing,
        "hops": hops or [],
        "final_answer": "answer",
        "outcome": outcome,
        "memory_facts_used": [],
        "explanation": None,
        "hop_limit_hit": 1 if hop_limit_hit else 0,
    }


def _hop(tool, status="success"):
    return {"tool": tool, "arguments": {}, "status": status, "latency_ms": 50.0}


# ─── _tool_stats helper ───────────────────────────────────────────────────────

def test_tool_stats_empty():
    assert _tool_stats([]) == {}


def test_tool_stats_counts_calls():
    traces = [
        _trace(hops=[_hop("github", "success"), _hop("github", "error")]),
        _trace(hops=[_hop("github", "success")]),
    ]
    stats = _tool_stats(traces)
    assert stats["github"]["total"] == 3
    assert stats["github"]["failed"] == 1


def test_tool_stats_empty_status_counts_as_failure():
    traces = [_trace(hops=[_hop("github", "empty")])]
    stats = _tool_stats(traces)
    assert stats["github"]["failed"] == 1


def test_tool_stats_multiple_tools():
    traces = [
        _trace(hops=[_hop("github", "success"), _hop("stackexchange", "error")])
    ]
    stats = _tool_stats(traces)
    assert "github" in stats
    assert "stackexchange" in stats
    assert stats["stackexchange"]["failed"] == 1


# ─── print_failure_report ─────────────────────────────────────────────────────

def test_failure_report_empty_traces(capsys):
    """Empty trace list prints a graceful message, does not crash."""
    console = Console(file=io.StringIO())
    with patch("observable_agent_panel.core.analyzer.console", console):
        print_failure_report([])
    output = console.file.getvalue()
    assert "No trace data" in output


def test_failure_report_counts_low_similarity():
    """Traces with score < 0.30 are counted as knowledge gaps."""
    traces = [
        _trace(run_id="a", score=0.10),
        _trace(run_id="b", score=0.25),
        _trace(run_id="c", score=0.90),
    ]
    buf = io.StringIO()
    console = Console(file=buf)
    with patch("observable_agent_panel.core.analyzer.console", console):
        print_failure_report(traces)
    output = buf.getvalue()
    # 2 low-similarity runs out of 3
    assert "2" in output


def test_failure_report_counts_hop_limit_hits():
    traces = [
        _trace(run_id="a", hop_limit_hit=True),
        _trace(run_id="b", hop_limit_hit=True),
        _trace(run_id="c", hop_limit_hit=False),
    ]
    buf = io.StringIO()
    with patch("observable_agent_panel.core.analyzer.console", Console(file=buf)):
        print_failure_report(traces)
    # 2 hop limit hits
    assert "2" in buf.getvalue()


def test_failure_report_counts_human_failures():
    traces = [
        _trace(run_id="a", outcome="n"),
        _trace(run_id="b", outcome="y"),
        _trace(run_id="c", outcome="n"),
    ]
    buf = io.StringIO()
    with patch("observable_agent_panel.core.analyzer.console", Console(file=buf)):
        print_failure_report(traces)
    assert "2" in buf.getvalue()


def test_failure_report_shows_tool_table():
    traces = [
        _trace(hops=[_hop("search_github_prs", "error"), _hop("search_github_prs", "success")])
    ]
    buf = io.StringIO()
    with patch("observable_agent_panel.core.analyzer.console", Console(file=buf)):
        print_failure_report(traces)
    assert "search_github_prs" in buf.getvalue()


# ─── print_trace_diff ─────────────────────────────────────────────────────────

def test_trace_diff_renders_both_runs():
    t1 = _trace(run_id="aaa111", query="CORS bug", routing="tools_only", score=0.31)
    t2 = _trace(run_id="bbb222", query="CORS bug", routing="memory_only", score=0.91)
    buf = io.StringIO()
    with patch("observable_agent_panel.core.analyzer.console", Console(file=buf)):
        print_trace_diff(t1, t2)
    output = buf.getvalue()
    assert "tools_only" in output
    assert "memory_only" in output
    assert "0.31" in output or "0.310" in output
    assert "0.91" in output or "0.910" in output


def test_trace_diff_hop_limit_field():
    t1 = _trace(run_id="x1", hop_limit_hit=True)
    t2 = _trace(run_id="x2", hop_limit_hit=False)
    buf = io.StringIO()
    with patch("observable_agent_panel.core.analyzer.console", Console(file=buf)):
        print_trace_diff(t1, t2)
    output = buf.getvalue()
    assert "YES" in output
    assert "no" in output


def test_trace_diff_outcome_field():
    t1 = _trace(run_id="y1", outcome="n")
    t2 = _trace(run_id="y2", outcome="y")
    buf = io.StringIO()
    with patch("observable_agent_panel.core.analyzer.console", Console(file=buf)):
        print_trace_diff(t1, t2)
    assert "n" in buf.getvalue()
    assert "y" in buf.getvalue()


# ─── print_anomaly_alerts ─────────────────────────────────────────────────────

def test_alerts_empty_traces():
    """Should not raise with no data."""
    buf = io.StringIO()
    with patch("observable_agent_panel.core.analyzer.console", Console(file=buf)):
        print_anomaly_alerts([])
    assert "Not enough data" in buf.getvalue()


def test_alerts_all_nominal():
    """Healthy data → 'All systems nominal' message."""
    traces = [_trace(run_id=str(i), score=0.88, hops=[_hop("github", "success")]) for i in range(5)]
    buf = io.StringIO()
    with patch("observable_agent_panel.core.analyzer.console", Console(file=buf)):
        print_anomaly_alerts(traces)
    assert "nominal" in buf.getvalue()


def test_alerts_fires_tool_failure_alert():
    """Tool failing > 50% of 5+ calls triggers alert."""
    bad_hop = _hop("search_github_prs", "error")
    traces = [_trace(run_id=str(i), hops=[bad_hop, bad_hop]) for i in range(5)]
    buf = io.StringIO()
    with patch("observable_agent_panel.core.analyzer.console", Console(file=buf)):
        print_anomaly_alerts(traces)
    assert "ALERT" in buf.getvalue()
    assert "search_github_prs" in buf.getvalue()


def test_alerts_fires_low_similarity_alert():
    """Average similarity < ALERT_LOW_SIMILARITY triggers alert."""
    traces = [_trace(run_id=str(i), score=0.15) for i in range(5)]
    buf = io.StringIO()
    with patch("observable_agent_panel.core.analyzer.console", Console(file=buf)):
        print_anomaly_alerts(traces)
    assert "ALERT" in buf.getvalue()
    assert "similarity" in buf.getvalue().lower()


def test_alerts_fires_hop_limit_alert():
    """Hop limit hit > 30% of recent runs triggers alert."""
    traces = [_trace(run_id=str(i), hop_limit_hit=(i < 4)) for i in range(10)]
    buf = io.StringIO()
    with patch("observable_agent_panel.core.analyzer.console", Console(file=buf)):
        print_anomaly_alerts(traces)
    assert "ALERT" in buf.getvalue()
    assert "hop" in buf.getvalue().lower()


def test_alerts_uses_only_recent_window():
    """
    Only the first RECENT_WINDOW traces are considered for alerts.
    Old failing traces beyond the window should not trigger an alert.
    """
    # First RECENT_WINDOW traces are healthy
    healthy = [_trace(run_id=str(i), score=0.95) for i in range(RECENT_WINDOW)]
    # Many stale bad traces appended after
    stale_bad = [_trace(run_id=str(i + 100), score=0.05) for i in range(50)]
    traces = healthy + stale_bad  # newest first in the list

    buf = io.StringIO()
    with patch("observable_agent_panel.core.analyzer.console", Console(file=buf)):
        print_anomaly_alerts(traces)
    # Healthy window → no similarity alert
    assert "nominal" in buf.getvalue()
