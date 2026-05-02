import pytest
import os
from devops_agent.memory.long_term import LongTermMemory

@pytest.fixture
def temp_memory():
    """Provides a clean in-memory database for testing."""
    return LongTermMemory(db_path=":memory:")

def test_add_and_search_memory(temp_memory):
    # Setup
    fact = {
        "issue": "Broken auth",
        "fix": "Update token",
        "context": "Integration test",
        "repo_name": "test/repo",
        "tags": ["auth"]
    }
    
    # Action
    row_id = temp_memory.add_memory(fact)
    assert row_id > 0
    
    # Search
    results = temp_memory.search_memory("How to fix auth?", top_k=1)
    assert len(results) > 0
    assert results[0]["issue"] == "Broken auth"
    assert results[0]["score"] > 0.5

def test_repo_filtering(temp_memory):
    # Add two facts from different repos
    temp_memory.add_memory({
        "issue": "FastAPI bug",
        "fix": "Fix it",
        "context": "Context",
        "repo_name": "tiangolo/fastapi",
        "tags": []
    })
    temp_memory.add_memory({
        "issue": "Django bug",
        "fix": "Fix it",
        "context": "Context",
        "repo_name": "django/django",
        "tags": []
    })
    
    # Search with filter
    results = temp_memory.search_memory("bug", top_k=10, repo_filter="tiangolo/fastapi")
    
    # Verify only fastapi result is returned (or at least it's the one we check)
    repos = [r["repo_name"] for r in results]
    assert "tiangolo/fastapi" in repos
    assert "django/django" not in repos
