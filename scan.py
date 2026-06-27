#!/usr/bin/env python3
"""Scan X, GitHub, HN, and Reddit for trending AI topics. Pick ideas to save."""

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import quote

IDEAS_FILE = Path(__file__).parent / "ideas.md"
SOCIALDATA_KEY = os.environ.get("SOCIALDATA_API_KEY", "")


def fetch_json(url: str, headers: dict | None = None, timeout: int = 10) -> dict | list | None:
    try:
        req = Request(url, headers=headers or {})
        with urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except Exception as e:
        print(f"  [skip] {e}")
        return None


# ── X (Twitter) via SocialData ──────────────────────────────────────

def scan_x() -> list[dict]:
    if not SOCIALDATA_KEY:
        print("  [skip] SOCIALDATA_API_KEY not set")
        return []

    since = (datetime.now(timezone.utc) - timedelta(days=3)).strftime("%Y-%m-%d")
    queries = [
        f'"ai" ("new" OR "just" OR "announced" OR "launched") min_faves:100 since:{since} lang:en',
        f'("vibe coding" OR "vibe coded" OR "claude code") min_faves:30 since:{since} lang:en',
        f'"open source" ("ai" OR "llm" OR "agent") min_faves:50 since:{since} lang:en',
        f'("supabase" OR "cursor" OR "bolt") ("built" OR "shipped") min_faves:30 since:{since} lang:en',
        f'("ai model" OR "new model" OR "frontier") ("released" OR "launched" OR "announced") min_faves:50 since:{since} lang:en',
    ]

    results = []
    seen = set()
    for q in queries:
        url = f"https://api.socialdata.tools/twitter/search?query={quote(q)}&type=Latest"
        data = fetch_json(url, {"Authorization": f"Bearer {SOCIALDATA_KEY}"})
        if not data or "tweets" not in data:
            continue
        for t in data["tweets"][:5]:
            tid = t.get("id_str", "")
            if tid in seen:
                continue
            seen.add(tid)
            user = t.get("user", {}).get("screen_name", "?")
            text = t.get("full_text", "").replace("\n", " ")[:200]
            likes = t.get("favorite_count", 0)
            results.append({
                "source": "X",
                "title": text,
                "url": f"https://x.com/{user}/status/{tid}",
                "score": likes,
                "meta": f"@{user} | {likes} likes",
            })

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:15]


# ── GitHub Trending ─────────────────────────────────────────────────

def scan_github() -> list[dict]:
    since = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
    queries = [
        f"ai created:>{since} stars:>50",
        f"llm created:>{since} stars:>50",
        f"vibe-coding created:>{since} stars:>20",
        f"agent created:>{since} stars:>100",
    ]

    results = []
    seen = set()
    for q in queries:
        url = f"https://api.github.com/search/repositories?q={quote(q)}&sort=stars&per_page=5"
        data = fetch_json(url, {"Accept": "application/vnd.github.v3+json"})
        if not data or "items" not in data:
            continue
        for r in data["items"]:
            name = r.get("full_name", "")
            if name in seen:
                continue
            seen.add(name)
            results.append({
                "source": "GitHub",
                "title": f"{name} — {r.get('description', 'No description')[:120]}",
                "url": r.get("html_url", ""),
                "score": r.get("stargazers_count", 0),
                "meta": f"★ {r.get('stargazers_count', 0)} | {r.get('language', '?')}",
            })

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:10]


# ── Hacker News ─────────────────────────────────────────────────────

def scan_hn() -> list[dict]:
    url = "https://hacker-news.firebaseio.com/v0/topstories.json"
    ids = fetch_json(url)
    if not ids:
        return []

    results = []
    ai_keywords = {"ai", "llm", "gpt", "claude", "model", "agent", "openai", "anthropic",
                   "gemini", "mistral", "coding", "vibe", "supabase", "cursor", "ml",
                   "neural", "transformer", "diffusion", "open source", "oss"}

    for story_id in ids[:50]:
        story = fetch_json(f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json")
        if not story or story.get("type") != "story":
            continue
        title = story.get("title", "").lower()
        if any(kw in title for kw in ai_keywords):
            results.append({
                "source": "HN",
                "title": story.get("title", ""),
                "url": story.get("url", f"https://news.ycombinator.com/item?id={story_id}"),
                "score": story.get("score", 0),
                "meta": f"{story.get('score', 0)} pts | {story.get('descendants', 0)} comments",
            })

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:10]


# ── Reddit ──────────────────────────────────────────────────────────

def scan_reddit() -> list[dict]:
    subs = ["artificial", "MachineLearning", "LocalLLaMA", "ChatGPT", "ClaudeAI"]
    results = []

    for sub in subs:
        url = f"https://www.reddit.com/r/{sub}/hot.json?limit=5"
        data = fetch_json(url, {"User-Agent": "short-form-workflow/1.0"})
        if not data or "data" not in data:
            continue
        for post in data["data"].get("children", []):
            d = post.get("data", {})
            if d.get("stickied"):
                continue
            results.append({
                "source": "Reddit",
                "title": d.get("title", "")[:200],
                "url": f"https://reddit.com{d.get('permalink', '')}",
                "score": d.get("score", 0),
                "meta": f"r/{sub} | {d.get('score', 0)} pts | {d.get('num_comments', 0)} comments",
            })

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:10]


# ── Display & Save ──────────────────────────────────────────────────

def display_results(all_results: list[dict]) -> None:
    print(f"\n{'='*60}")
    print(f"  Found {len(all_results)} trending AI topics")
    print(f"{'='*60}\n")

    for i, r in enumerate(all_results, 1):
        src = r["source"].ljust(6)
        print(f"  [{i:2d}] [{src}] {r['title'][:100]}")
        print(f"       {r['meta']}")
        print(f"       {r['url']}")
        print()


def save_ideas(all_results: list[dict], picks: list[int]) -> None:
    if not picks:
        print("No ideas saved.")
        return

    today = datetime.now().strftime("%Y-%m-%d")

    # Read existing content
    existing = ""
    if IDEAS_FILE.exists():
        existing = IDEAS_FILE.read_text()

    # Build new entries
    new_entries = []
    for idx in picks:
        if 1 <= idx <= len(all_results):
            r = all_results[idx - 1]
            new_entries.append(
                f"- [ ] **[{r['source']}]** {r['title'][:120]}\n"
                f"  - {r['meta']}\n"
                f"  - {r['url']}\n"
            )

    if not new_entries:
        print("No valid picks.")
        return

    # Append to file
    section = f"\n## {today}\n\n" + "\n".join(new_entries) + "\n"

    if not existing:
        content = "# Video Ideas\n\nSaved from `scan.py` — trending AI topics worth making videos about.\n" + section
    else:
        content = existing + section

    IDEAS_FILE.write_text(content)
    print(f"\n  Saved {len(new_entries)} ideas to {IDEAS_FILE}")


# ── Main ────────────────────────────────────────────────────────────

def main():
    source_filter = sys.argv[1] if len(sys.argv) > 1 else None

    scanners = {
        "x": ("X (Twitter)", scan_x),
        "github": ("GitHub", scan_github),
        "hn": ("Hacker News", scan_hn),
        "reddit": ("Reddit", scan_reddit),
    }

    if source_filter and source_filter not in scanners:
        print(f"Unknown source: {source_filter}")
        print(f"Available: {', '.join(scanners.keys())}")
        return

    all_results = []

    for key, (name, scanner) in scanners.items():
        if source_filter and key != source_filter:
            continue
        print(f"Scanning {name}...")
        results = scanner()
        all_results.extend(results)
        print(f"  Found {len(results)} results")

    if not all_results:
        print("\nNo results found.")
        return

    display_results(all_results)

    # Pick mode
    print("Enter numbers to save (comma-separated), or 'q' to quit:")
    print("Example: 1,3,7\n")

    try:
        choice = input("> ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\nBye!")
        return

    if choice.lower() in ("q", "quit", ""):
        print("No ideas saved. Bye!")
        return

    picks = []
    for part in choice.split(","):
        part = part.strip()
        if part.isdigit():
            picks.append(int(part))

    save_ideas(all_results, picks)


if __name__ == "__main__":
    main()
