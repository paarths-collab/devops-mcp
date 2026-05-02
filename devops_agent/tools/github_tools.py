"""
GitHub tool implementations for Observable Agent Control Panel.
All external API calls go through here.
"""

import os
import requests
from typing import Dict, List, Optional

# Demo target repository (configurable via env)
_DEFAULT_REPO = os.getenv("TARGET_REPO", "tiangolo/fastapi")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
MAX_DIFF_LENGTH = 3000  # NFR2: Context safety

# Global context for the active repository
_CURRENT_REPO = _DEFAULT_REPO
_STORED_REPOS = [_DEFAULT_REPO] if _DEFAULT_REPO else []

def get_current_repo() -> str:
    return _CURRENT_REPO

def set_current_repo(repo: str) -> None:
    global _CURRENT_REPO
    _CURRENT_REPO = repo
    if repo not in _STORED_REPOS:
        _STORED_REPOS.append(repo)

def get_stored_repos() -> List[str]:
    return _STORED_REPOS

def _headers() -> Dict[str, str]:
    """Build request headers; inject PAT if available."""
    h = {"Accept": "application/vnd.github.v3+json"}
    if GITHUB_TOKEN:
        h["Authorization"] = f"token {GITHUB_TOKEN}"
    return h


def search_github_prs(query: str, repo: Optional[str] = None) -> Dict:
    """
    Search closed PRs in the target repository matching a query string.
    Uses the REST pulls endpoint filtered locally to avoid GitHub search API restrictions.
    """
    repo = repo or get_current_repo()
    url = f"https://api.github.com/repos/{repo}/pulls"
    
    try:
        resp = requests.get(
            url,
            headers=_headers(),
            params={"state": "closed", "per_page": 50, "sort": "updated", "direction": "desc"},
            timeout=20
        )
        if not resp.ok:
            error_data = {}
            try:
                error_data = resp.json()
            except:
                pass
            error_msg = error_data.get("message", resp.text)
            return {
                "status": "error",
                "message": f"GitHub API error ({resp.status_code}): {error_msg}",
                "results": [],
            }

        prs = resp.json()
        query_terms = query.lower().split()
        
        matched = []
        for pr in prs:
            title = (pr.get("title") or "").lower()
            body = (pr.get("body") or "").lower()
            # Basic term matching for reliability
            if any(term in title or term in body for term in query_terms):
                matched.append({
                    "number": pr.get("number"),
                    "title": pr.get("title"),
                    "url": pr.get("html_url"),
                    "state": pr.get("state"),
                })

        if not matched:
            return {
                "status": "empty",
                "message": f"No closed PRs found matching '{query}' in {repo}.",
                "results": [],
            }

        return {
            "status": "success",
            "total_count": len(matched),
            "results": matched[:5],
        }

    except requests.RequestException as e:
        return {
            "status": "error",
            "message": f"GitHub API request failed: {str(e)}",
            "results": [],
        }

    except requests.RequestException as e:
        return {
            "status": "error",
            "message": f"GitHub API request failed: {str(e)}",
            "results": [],
        }


def fetch_pr_diff(pr_number: int, repo: Optional[str] = None) -> Dict:
    """
    Fetch the code diff and description for a specific Pull Request.
    The 'pr_number' MUST be an integer.
    CRITICAL: Truncate the returned diff to 3,000 characters maximum.
    """
    repo = repo or get_current_repo()
    # GitHub PR endpoint
    url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}"

    try:
        resp = requests.get(url, headers=_headers(), timeout=20)
        resp.raise_for_status()
        pr_data = resp.json()

        # Fetch the actual diff text
        diff_url = pr_data.get("diff_url")
        if not diff_url:
            return {
                "status": "error",
                "message": f"No diff_url found for PR #{pr_number}.",
                "diff": "",
                "truncated": False,
            }

        diff_resp = requests.get(diff_url, headers=_headers(), timeout=20)
        diff_resp.raise_for_status()
        raw_diff = diff_resp.text

        # NFR2: Truncate to prevent context window overflow
        truncated = False
        if len(raw_diff) > MAX_DIFF_LENGTH:
            raw_diff = raw_diff[:MAX_DIFF_LENGTH]
            truncated = True

        return {
            "status": "success",
            "pr_number": pr_number,
            "title": pr_data.get("title"),
            "body": pr_data.get("body", ""),
            "diff": raw_diff,
            "truncated": truncated,
            "original_length": len(diff_resp.text),
        }

    except requests.RequestException as e:
        return {
            "status": "error",
            "message": f"GitHub API request failed: {str(e)}",
            "diff": "",
            "truncated": False,
        }

def get_closed_prs(repo: Optional[str] = None, count: int = 10) -> Dict:
    """
    Fetch a list of the most recent closed PRs for indexing purposes.
    """
    repo = repo or get_current_repo()
    url = f"https://api.github.com/repos/{repo}/pulls?state=closed&per_page={count}"
    
    try:
        resp = requests.get(url, headers=_headers(), timeout=20)
        resp.raise_for_status()
        prs = resp.json()
        
        results = []
        for pr in prs:
            results.append({
                "number": pr.get("number"),
                "title": pr.get("title"),
                "url": pr.get("html_url")
            })
            
        return {
            "status": "success",
            "repo": repo,
            "results": results
        }
    except requests.RequestException as e:
        return {
            "status": "error",
            "message": f"Failed to fetch closed PRs: {str(e)}"
        }

def get_repo_issues(repo: Optional[str] = None, count: int = 10) -> Dict:
    """
    Fetch a list of the most recent closed issues (often containing bug reports) for indexing.
    """
    repo = repo or get_current_repo()
    url = f"https://api.github.com/repos/{repo}/issues?state=closed&per_page={count}"
    
    try:
        resp = requests.get(url, headers=_headers(), timeout=20)
        resp.raise_for_status()
        issues = resp.json()
        
        results = []
        for issue in issues:
            # Skip PRs (GitHub Issues API returns both)
            if "pull_request" in issue:
                continue
                
            results.append({
                "number": issue.get("number"),
                "title": issue.get("title"),
                "body": issue.get("body", ""),
                "url": issue.get("html_url")
            })
            
        return {
            "status": "success",
            "repo": repo,
            "results": results[:count]
        }
    except requests.RequestException as e:
        return {
            "status": "error",
            "message": f"Failed to fetch closed issues: {str(e)}"
        }
