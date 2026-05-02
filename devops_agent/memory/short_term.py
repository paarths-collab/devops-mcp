"""
Short-term memory module for OctaClaw MCP.
Simple sliding window holding the last N messages.
"""

from collections import deque
from typing import List, Dict, Optional


class ShortTermMemory:
    """
    Sliding window of recent conversation turns.
    Stores at most `max_turns` messages (default 4 = 2 user + 2 assistant).
    """

    def __init__(self, max_turns: int = 4) -> None:
        self.max_turns: int = max_turns
        self.buffer: deque = deque(maxlen=max_turns)

    def add(self, role: str, content: str) -> None:
        """Append a message dict to the sliding window."""
        self.buffer.append({"role": role, "content": content})

    def get_context(self) -> List[Dict[str, str]]:
        """Return the current buffer as a list of message dicts."""
        return list(self.buffer)

    def last_user_query(self) -> Optional[str]:
        """Helper: return the most recent user message content."""
        for msg in reversed(self.buffer):
            if msg["role"] == "user":
                return msg["content"]
        return None

    def clear(self) -> None:
        """Wipe the short-term buffer."""
        self.buffer.clear()
