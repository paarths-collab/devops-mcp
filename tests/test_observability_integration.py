"""
Integration tests for the new observability data functions and CLI commands.
"""

import pytest
from observable_agent_panel.core.analyzer import get_failure_report_data, get_anomaly_alerts_data
from observable_agent_panel.core.trace_db import TraceDB
import os

def _trace(run_id="abc", score=0.5, hops=None, outcome=None, hop_limit_hit=False):
    return {
        "run_id": run_id,
        "timestamp": "2026-05-01T10:00:00",
        "query": "test",
        "similarity_score": score,
        "routing_decision": "tools_only",
        "hops": hops or [],
        "outcome": outcome,
        "hop_limit_hit": 1 if hop_limit_hit else 0,
    }

def _hop(tool, status="success"):
    return {"tool": tool, "status": status}

def test_get_failure_report_data():
    traces = [
        _trace(run_id="1", outcome="y", hops=[_hop("github")]),
        _trace(run_id="2", outcome="n", hops=[_hop("github", "error")]),
        _trace(run_id="3", outcome="n", hop_limit_hit=True),
        _trace(run_id="4", score=0.1) # knowledge gap
    ]
    data = get_failure_report_data(traces)
    
    assert data["total_runs"] == 4
    assert data["success_rate"] == 1/3 # 1 yes, 2 no
    assert data["knowledge_gaps"] == 1
    assert data["hop_limit_hits"] == 1
    assert data["human_failures"] == 2
    assert data["tool_stats"]["github"]["total"] == 2
    assert data["tool_stats"]["github"]["success"] == 1

def test_get_anomaly_alerts_data_tool_spike():
    # 5 runs with failing github tool
    traces = [_trace(run_id=str(i), hops=[_hop("github", "error")]) for i in range(5)]
    alerts = get_anomaly_alerts_data(traces)
    
    assert len(alerts) > 0
    assert any(a["type"] == "tool_failure" and a["tool"] == "github" for a in alerts)

def test_get_anomaly_alerts_data_low_sim():
    traces = [_trace(run_id=str(i), score=0.1) for i in range(10)]
    alerts = get_anomaly_alerts_data(traces)
    
    assert any(a["type"] == "low_similarity" for a in alerts)

def test_get_anomaly_alerts_data_hop_limit():
    traces = [_trace(run_id=str(i), hop_limit_hit=True) for i in range(10)]
    alerts = get_anomaly_alerts_data(traces)
    
    assert any(a["type"] == "hop_limit_exhausted" for a in alerts)

def test_get_anomaly_alerts_data_nominal():
    traces = [_trace(run_id=str(i), score=0.9, hops=[_hop("github")]) for i in range(10)]
    alerts = get_anomaly_alerts_data(traces)
    assert len(alerts) == 0
