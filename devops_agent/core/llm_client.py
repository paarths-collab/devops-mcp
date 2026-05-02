"""
LLM client wrapper for Groq API.
Handles chat completions and tool-calling interactions.
"""

import os
import json
from typing import Any, Dict, List, Optional
from groq import Groq

# Model config
MODEL_NAME = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
MAX_TOKENS = int(os.getenv("GROQ_MAX_TOKENS", "4096"))
TEMPERATURE = float(os.getenv("GROQ_TEMPERATURE", "0.2"))


class LLMClient:
    """Minimal Groq client with tool support."""

    def __init__(self, api_key: Optional[str] = None) -> None:
        self.api_key = api_key or os.getenv("GROQ_API_KEY")
        if not self.api_key:
            raise ValueError(
                "Groq API key is required. Set GROQ_API_KEY environment variable."
            )
        self.client = Groq(api_key=self.api_key)

    def chat(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: str = "auto",
    ) -> Dict[str, Any]:
        """
        Send messages to Groq LLM.
        If tools are provided, the model may return tool_calls.
        """
        kwargs: Dict[str, Any] = {
            "model": MODEL_NAME,
            "messages": messages,
            "temperature": TEMPERATURE,
            "max_tokens": MAX_TOKENS,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = tool_choice

        response = self.client.chat.completions.create(**kwargs)
        return response.model_dump()

    def simple_chat(self, messages: List[Dict[str, str]]) -> str:
        """
        Convenience: chat without tools, return the assistant's text.
        """
        resp = self.chat(messages)
        choice = resp["choices"][0]
        return choice["message"].get("content", "")

    def summarize_for_memory(self, user_query: str, tool_results: str, answer: str) -> Dict[str, Any]:
        """
        Ask the LLM to distill the interaction into a compact memory JSON.
        Returns a dict: {"issue": str, "fix": str, "context": str, "tags": list}
        """
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a compression engine. Summarize the bug and fix "
                    "into a JSON object with exactly four keys: 'issue', 'fix', "
                    "'context', and 'tags'. The 'tags' value must be a JSON array. "
                    "Be concise but specific. Output ONLY raw JSON, no markdown."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"User Query: {user_query}\n"
                    f"Tool Results: {tool_results[:2000]}\n"
                    f"Final Answer: {answer}\n"
                    f"\nSummarize into JSON: "
                    f"{{\"issue\": \"...\", \"fix\": \"...\", "
                    f"\"context\": \"...\", \"tags\": [\"...\"]}}"
                ),
            },
        ]
        raw = self.simple_chat(messages).strip()
        # Strip markdown code fences if present
        if raw.startswith("```json"):
            raw = raw[7:]
        if raw.startswith("```"):
            raw = raw[3:]
        if raw.endswith("```"):
            raw = raw[:-3]
        raw = raw.strip()

        try:
            parsed = json.loads(raw)
            tags = parsed.get("tags", [])
            if not isinstance(tags, list):
                tags = [str(tags)]
            return {
                "issue": parsed.get("issue", user_query),
                "fix": parsed.get("fix", answer),
                "context": parsed.get("context", ""),
                "tags": tags,
            }
        except json.JSONDecodeError:
            # Fallback: use the whole answer as fix
            return {"issue": user_query, "fix": answer, "context": "", "tags": []}

    def summarize_pr(self, repo_name: str, pr_number: int, title: str, description: str, diff: str) -> Dict[str, Any]:
        """
        Summarize a GitHub PR into a structured fact for memory.
        """
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a DevOps intelligence engine. Analyze the provided GitHub PR "
                    "(title, description, and diff) and extract the core issue it solves and "
                    "the exact fix implemented. Output a JSON object with: "
                    "'issue', 'fix', 'context', and 'tags' (array). "
                    "Output ONLY raw JSON."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Repo: {repo_name}\n"
                    f"PR #{pr_number}: {title}\n"
                    f"Description: {description[:1000]}\n"
                    f"Diff Snippet: {diff[:2000]}\n"
                ),
            },
        ]
        raw = self.simple_chat(messages).strip()
        # Clean markdown
        raw = raw.replace("```json", "").replace("```", "").strip()

        try:
            parsed = json.loads(raw)
            return {
                "issue": parsed.get("issue", title),
                "fix": parsed.get("fix", "See PR diff"),
                "context": f"Extracted from {repo_name} PR #{pr_number}",
                "repo_name": repo_name,
                "tags": parsed.get("tags", []),
            }
        except Exception:
            return {
                "issue": title,
                "fix": "Review PR diff",
                "context": f"Extracted from {repo_name} PR #{pr_number}",
                "repo_name": repo_name,
                "tags": ["github", "pr", repo_name],
            }
