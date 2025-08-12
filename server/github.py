from typing import Any,List, Dict, Any, Optional
import httpx 
from mcp.server.fastmcp import FastMCP
from dotenv import load_dotenv
import os
import re
from datetime import datetime, timezone

#Claude Implementation
load_dotenv()
Github_token=os.getenv("GITHUB_API_KEY") # type: ignore
owner=os.getenv("OWNER") # type: ignore

#Initializing FastMCP server
mcp=FastMCP("Github")

#Constants
GITHUB_API_BASE="https://api.github.com"
USER_AGENT="github-app/1.0"
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")

ALLOWED_PATTERNS = {
    r.strip().lower()
    for r in os.getenv("GH_ALLOWED_REPOS", "").split(",")
    if r.strip()
}

ALLOWED_REPOS = os.getenv("GH_ALLOWED_REPOS")

async def make_github_request(url:str, method:str="GET", params: Dict[str, Any] | None = None, json: Dict[str, Any] |None = None) -> dict|list|None:
    '''Make a request to Github API'''
    if not Github_token:
        return {"Error": "GitHub API token is not set"}
    headers={
        "User-Agent": USER_AGENT,
        "Authorization": f"Bearer {Github_token}",
        "Accept": "application/vnd.github.v3+json"
    }
    async with httpx.AsyncClient() as client:
        try:
            if method=="GET":
                response=await client.get(url, headers=headers, params=params, timeout=30)
            elif method=="POST":
                response=await client.post(url, headers=headers, json=json, timeout=30)
            else:
                response=await client.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            return {"Error": f"Request failed: {str(e)}"}
        
async def paginate(
    url: str,
    *,
    params: Dict[str, Any] | None = None,
) -> List[dict]:
    """Collect paginated results (per_page=100) until exhausted."""
    results: List[dict] = []
    page = 1
    while True:
        page_params = dict(params or {})
        page_params.update({"per_page": 100, "page": page})
        data = await make_github_request(url, method="GET", params=page_params)
        if not isinstance(data, list) or not data:
            break
        results.extend(data)
        if len(data) < 100:
            break
        page += 1
    return results

def _pattern_allows(full: str) -> bool:
    """Check repo against ALLOWED_PATTERNS (empty => no restriction)."""
    if not ALLOWED_PATTERNS:
        return True
    full = full.lower()
    owner, _ = full.split("/", 1)
    for pat in ALLOWED_PATTERNS:
        if pat == "*":
            return True
        if pat.endswith("/*") and owner == pat[:-2]:
            return True
        if pat == full:
            return True
    return False


def validate_repo(repo: str) -> str | None:
    """Validate repo format and allow-list."""
    repo = (repo or "").strip()
    if not REPO_RE.match(repo):
        return "Invalid repo. Use 'owner/name'."
    if not _pattern_allows(repo):
        return f"Repo '{repo}' not allowed by GH_ALLOWED_REPOS."
    return None


def iso_age_days(iso_ts: str | None) -> int | None:
    """Return age in days for an ISO timestamp."""
    if not iso_ts:
        return None
    try:
        dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - dt).days
    except Exception:
        return None


def format_issue(item: dict) -> str:
    return (
        f"#{item.get('number')} [{item.get('state')}] {item.get('title')}\n"
        f"URL: {item.get('html_url')}"
    )


def format_pr(item: dict) -> str:
    return (
        f"PR #{item.get('number')} {item.get('title')} by {item.get('user', {}).get('login')}\n"
        f"Head: {item.get('head', {}).get('ref')}  Base: {item.get('base', {}).get('ref')}\n"
        f"URL: {item.get('html_url')}"
    )


def format_repo_activity(repo: dict) -> str:
    flags = []
    if repo.get("private"):
        flags.append("private")
    if repo.get("fork"):
        flags.append("fork")
    if repo.get("archived"):
        flags.append("archived")
    last = repo.get("last_activity") or "N/A"
    age = iso_age_days(repo.get("last_activity"))
    age_txt = f"{age} days ago" if age is not None else "unknown"
    return (
        f"{repo.get('repo')}"
        f"{' [' + ','.join(flags) + ']' if flags else ''}\n"
        f"Default branch: {repo.get('default_branch')}\n"
        f"Last activity: {last} ({age_txt})\n"
        f"URL: {repo.get('html_url')}"
    )


@mcp.tool()
async def gh_search_issues(repo: str, q: str, state: str = "open", limit: int = 10) -> str:
    """Search issues in a repository (returns a readable list)."""
    if err := validate_repo(repo):
        return err
    query = f"repo:{repo} is:issue state:{state} {q}".strip()
    url = f"{GITHUB_API_BASE}/search/issues"
    data = await make_github_request(url, params={"q": query, "per_page": min(limit, 100)})
    if isinstance(data, dict) and data.get("error"):
        return data["error"]
    if not isinstance(data, dict) or "items" not in data:
        return "No results or request failed."
    items = data.get("items", [])[:limit]
    if not items:
        return "No matching issues."
    return "\n\n---\n\n".join(format_issue(it) for it in items)


@mcp.tool()
async def gh_open_issue(repo: str, title: str, body: str = "", labels_csv: str = "") -> str:
    """Open an issue in a repository. labels_csv=comma-separated labels."""
    if err := validate_repo(repo):
        return err
    labels = [l.strip() for l in labels_csv.split(",") if l.strip()]
    url = f"{GITHUB_API_BASE}/repos/{repo}/issues"
    created = await make_github_request(url, method="POST", json={"title": title, "body": body, "labels": labels})
    if isinstance(created, dict) and created.get("error"):
        return created["error"]
    if not isinstance(created, dict) or "html_url" not in created:
        return "Failed to create issue."
    return f"Issue created: #{created.get('number')} — {created.get('html_url')}"


@mcp.tool()
async def gh_comment_issue(repo: str, number: int, body: str) -> str:
    """Add a comment to an existing issue/PR."""
    if err := validate_repo(repo):
        return err
    url = f"{GITHUB_API_BASE}/repos/{repo}/issues/{number}/comments"
    res = await make_github_request(url, method="POST", json={"body": body})
    if isinstance(res, dict) and res.get("error"):
        return res["error"]
    if not isinstance(res, dict) or "html_url" not in res:
        return "Failed to add comment."
    return f"Comment added: {res.get('html_url')}"


@mcp.tool()
async def gh_list_prs(repo: str, state: str = "open", limit: int = 10) -> str:
    """List PRs in a repository."""
    if err := validate_repo(repo):
        return err
    url = f"{GITHUB_API_BASE}/repos/{repo}/pulls"
    prs = await make_github_request(url, params={"state": state, "per_page": min(limit, 100)})
    if isinstance(prs, dict) and prs.get("error"):
        return prs["error"]
    if not isinstance(prs, list) or not prs:
        return "No PRs found."
    return "\n\n---\n\n".join(format_pr(pr) for pr in prs[:limit])


@mcp.tool()
async def gh_get_pr_files(repo: str, number: int, limit: int = 50) -> str:
    """Show changed files for a PR."""
    if err := validate_repo(repo):
        return err
    url = f"{GITHUB_API_BASE}/repos/{repo}/pulls/{number}/files"
    files = await make_github_request(url, params={"per_page": min(limit, 100)})
    if isinstance(files, dict) and files.get("error"):
        return files["error"]
    if not isinstance(files, list) or not files:
        return "No files found or request failed."
    lines = []
    for f in files[:limit]:
        lines.append(
            f"{f.get('filename')}  (+{f.get('additions')} / -{f.get('deletions')}, {f.get('changes')} changes)\n"
            f"Status: {f.get('status')}  Blob: {f.get('blob_url')}"
        )
    return "\n\n---\n\n".join(lines)


@mcp.tool()
async def gh_last_activity(
    owner: str = owner,  # Default owner
    owner_type: str = "user",   # "user" | "org" | "me"
    method: str = "pushed_at",  # "pushed_at" (fast) | "commit_api" (precise)
    include_forks: bool = False,
    include_archived: bool = False,
    max_repos: int = 500,
    sort: str = "stale"         # "stale" | "recent"
) -> str:
    """List repos with the last code activity time (readable summary)."""
    # Choose listing endpoint
    if owner == "me":
        list_url = f"{GITHUB_API_BASE}/user/repos"
        params = {
            "visibility": "all",
            "affiliation": "owner,collaborator,organization_member",
            "type": "all",
            "sort": "pushed",
        }
    elif owner_type == "org":
        list_url = f"{GITHUB_API_BASE}/orgs/{owner}/repos"
        params = {"type": "all", "sort": "pushed"}
    else:
        list_url = f"{GITHUB_API_BASE}/users/{owner}/repos"
        params = {"type": "all", "sort": "pushed"}

    repos = await paginate(list_url, params=params)
    if not repos:
        return "No repositories found or request failed."

    summary: List[str] = []
    count = 0
    for r in repos:
        if count >= max_repos:
            break
        if (not include_forks and r.get("fork")) or (not include_archived and r.get("archived")):
            continue

        full = r.get("full_name")
        if not _pattern_allows(full): # type: ignore
            continue

        default_branch = r.get("default_branch") or "main"
        last_iso = r.get("pushed_at")
        source = "pushed_at"

        if method == "commit_api":
            commits_url = f"{GITHUB_API_BASE}/repos/{full}/commits"
            commit = await make_github_request(commits_url, params={"sha": default_branch, "per_page": 1})
            if isinstance(commit, dict) and commit.get("error"):
                # keep pushed_at fallback, but add note
                source = f"{source} (commit_api_failed)"
            elif isinstance(commit, list) and commit:
                c = commit[0].get("commit", {})
                last_iso = (c.get("committer") or c.get("author") or {}).get("date", last_iso)
                source = "commit_api"

        line = format_repo_activity({
            "repo": full,
            "private": r.get("private", False),
            "fork": r.get("fork", False),
            "archived": r.get("archived", False),
            "default_branch": default_branch,
            "last_activity": last_iso,
            "html_url": r.get("html_url"),
        })
        summary.append(line + f"\nSource: {source}")
        count += 1

    # Sort the output by age (older first if "stale", newest first if "recent")
    def key_fn(s: str):
        try:
            marker = "Last activity: "
            start = s.index(marker) + len(marker)
            iso = s[start:].split(" ", 1)[0]
            age = iso_age_days(iso)
            return (age is None, age or 10**9)
        except Exception:
            return (True, 10**9)

    summary.sort(key=key_fn, reverse=(sort == "recent"))
    return "\n\n====\n\n".join(summary)

@mcp.tool()
async def gh_diag() -> str:
    """Diagnose GitHub auth + allow-list + whoami."""
    who = await make_github_request(f"{GITHUB_API_BASE}/user")
    login = who.get("login") if isinstance(who, dict) else None
    allowed = ", ".join(sorted(ALLOWED_PATTERNS)) if ALLOWED_PATTERNS else "(no restriction)"
    return (
        f"token_set={bool(Github_token)} | "
        f"user_login={login or who} | "
        f"allowed_patterns={allowed}"
    )

@mcp.resource("echo://{message}")
def echo(message:str) -> str:
    """Echo a message as a resource"""
    return f"Resource echo: {message}"