import pytest
from devops_agent.memory.long_term import LongTermMemory
import os

def test_duplicate_prevention():
    # Use an in-memory DB for speed and isolation
    memory = LongTermMemory(db_path=":memory:")
    
    fact = {
        "issue": "Connection timeout in database",
        "fix": "Increase timeout to 30s",
        "repo_name": "test-repo"
    }
    
    id1 = memory.add_memory(fact)
    id2 = memory.add_memory(fact)
    
    # Should return the same ID and not create a new row
    assert id1 == id2
    
    # Check count
    facts = memory.list_facts()
    assert len(facts) == 1
