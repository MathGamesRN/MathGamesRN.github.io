#!/usr/bin/env python3
"""

game_manager.py — Download GitHub repos/subfolders, and manage a games JS registry.

─── Subcommands ────────────────────────────────────────────────────────────────

  download <github_url> [output_dir]
      Download a GitHub repo or subfolder.

      Examples:
          python game_manager.py download https://github.com/owner/repo
          python game_manager.py download https://github.com/owner/repo/tree/main/src/utils
          python game_manager.py download https://github.com/owner/repo/tree/main/src/utils ./my_output

  add <games.js> <games.md> [games_dir] [--debug] [--workers N]
      Append new games from a markdown list into a GAMES JS file,
      then download each new game's files into <games_dir>/<id>/.

      games_dir  — root folder where game files are saved (default: ./games)
                   Each game lands in <games_dir>/<id>/

      --workers N — number of parallel download threads (default: 4)

      Failed downloads are appended to download_failures.log in the current directory.

      Markdown format (single port):
        - [Title](https://github.com/owner/repo) - port by [name](url)

      Markdown format (multiple ports):
        - [Title](url1), [2](url2), [3](url3) - Ports by [porter1](url), [porter2](url)

      URL selection priority:
        1. Any URL whose path contains 'genizy' (bread's account)
        2. The last URL listed (highest number)

─── Authentication ──────────────────────────────────────────────────────────────

  Set the GITHUB_TOKEN environment variable to avoid API rate limits:
      export GITHUB_TOKEN=ghp_yourtoken   # Linux/macOS
      set GITHUB_TOKEN=ghp_yourtoken      # Windows CMD
  Tokens can be created at: https://github.com/settings/tokens
  No special scopes are needed for public repos.
"""

import os
import re
import sys
import json
import zipfile
import shutil
import tempfile
import threading
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


BREAD_GITHUB = "genizy"
FAILURE_LOG  = Path("download_failures.log")

# Lock so parallel downloads don't interleave their console output or log writes
_print_lock = threading.Lock()

def locked_print(*args, **kwargs):
    with _print_lock:
        print(*args, **kwargs)

def log_failure(title: str, game_id: int, repo_url: str, reason: str) -> None:
    """Append a failure entry to FAILURE_LOG (thread-safe)."""
    import datetime
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] id={game_id} | {title!r} | {repo_url} | {reason}\n"
    with _print_lock:
        with open(FAILURE_LOG, "a", encoding="utf-8") as f:
            f.write(line)


# ══════════════════════════════════════════════════════════════════════════════
# gh_download — URL parsing, HTTP helpers, download strategies
# ══════════════════════════════════════════════════════════════════════════════

def parse_github_url(url: str) -> dict:
    """
    Parse a GitHub URL and return its components.

    Supported forms:
      https://github.com/owner/repo
      https://github.com/owner/repo/tree/<branch>
      https://github.com/owner/repo/tree/<branch>/path/to/folder
    """
    url = url.rstrip("/")

    repo_only = re.fullmatch(
        r"https?://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)",
        url,
    )
    if repo_only:
        return {
            "owner":     repo_only.group("owner"),
            "repo":      repo_only.group("repo"),
            "branch":    None,
            "folder":    None,
            "is_folder": False,
        }

    tree_pattern = re.fullmatch(
        r"https?://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)"
        r"/tree/(?P<branch>[^/]+)(?:/(?P<folder>.+))?",
        url,
    )
    if tree_pattern:
        folder = tree_pattern.group("folder")
        return {
            "owner":     tree_pattern.group("owner"),
            "repo":      tree_pattern.group("repo"),
            "branch":    tree_pattern.group("branch"),
            "folder":    folder,
            "is_folder": folder is not None,
        }

    raise ValueError(
        f"Unrecognised GitHub URL format: {url}\n"
        "Expected: https://github.com/owner/repo[/tree/branch[/path]]"
    )


def _build_headers() -> dict:
    """Return request headers, including a Bearer token if GITHUB_TOKEN is set."""
    headers = {"User-Agent": "gh-download/1.0"}
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def http_get(url: str, *, as_bytes: bool = False):
    from urllib.parse import urlsplit, urlunsplit, quote
    parts = urlsplit(url)
    safe_path = quote(parts.path, safe="/:@!$&'()*+,;=")
    url = urlunsplit(parts._replace(path=safe_path))

    req = urllib.request.Request(url, headers=_build_headers())
    with urllib.request.urlopen(req) as resp:
        return resp.read() if as_bytes else resp.read().decode()


def default_branch(owner: str, repo: str) -> str:
    """Ask the GitHub API for the repo's default branch."""
    api = f"https://api.github.com/repos/{owner}/{repo}"
    try:
        data = json.loads(http_get(api))
        return data["default_branch"]
    except Exception:
        return "main"


def _download_zip(owner: str, repo: str, branch: str) -> bytes:
    """Download the full repo zip and return the raw bytes."""
    zip_url = f"https://github.com/{owner}/{repo}/archive/refs/heads/{branch}.zip"
    locked_print(f"  Fetching zip from {zip_url} …")
    return http_get(zip_url, as_bytes=True)


def download_repo(owner: str, repo: str, branch: str, dest: Path) -> None:
    """Download the entire repo as a zip archive and extract it."""
    locked_print(f"Downloading full repo '{owner}/{repo}' (branch: {branch}) …")
    zip_bytes = _download_zip(owner, repo, branch)

    zip_path = dest / f"{repo}-{branch}.zip"
    zip_path.write_bytes(zip_bytes)

    locked_print(f"Extracting to '{dest}' …")
    with tempfile.TemporaryDirectory() as tmp:
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(tmp)
        zip_path.unlink()

        extracted = Path(tmp) / f"{repo}-{branch}"
        for item in extracted.iterdir():
            target = dest / item.name
            if target.exists():
                shutil.rmtree(target) if target.is_dir() else target.unlink()
            shutil.move(str(item), dest)

    locked_print(f"✓ Repo contents saved to: {dest}")


def _folder_via_api(
    owner: str, repo: str, branch: str, folder: str, dest: Path
) -> None:
    """
    Download a subfolder using the Git Trees API (requires API access).
    Raises urllib.error.HTTPError if rate-limited or forbidden.
    """
    tree_url = (
        f"https://api.github.com/repos/{owner}/{repo}"
        f"/git/trees/{branch}?recursive=1"
    )
    locked_print("  Trying GitHub Trees API …")
    tree_data = json.loads(http_get(tree_url))

    if tree_data.get("truncated"):
        locked_print("  Warning: tree was truncated by GitHub (very large repo). "
              "Some files may be missing.")

    prefix = folder.rstrip("/") + "/"
    blobs  = [
        item for item in tree_data.get("tree", [])
        if item["type"] == "blob" and item["path"].startswith(prefix)
    ]

    if not blobs:
        raise FileNotFoundError(
            f"No files found under '{folder}' on branch '{branch}'."
        )

    dest.mkdir(parents=True, exist_ok=True)

    raw_base = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/"
    locked_print(f"  Downloading {len(blobs)} file(s) …")

    for item in blobs:
        rel_path  = item["path"][len(prefix):]
        file_dest = dest / rel_path
        file_dest.parent.mkdir(parents=True, exist_ok=True)
        raw_url = raw_base + item["path"]
        try:
            file_dest.write_bytes(http_get(raw_url, as_bytes=True))
            locked_print(f"    ✓ {rel_path}")
        except urllib.error.HTTPError as exc:
            locked_print(f"    ✗ {rel_path} — {exc}")

    locked_print(f"\n✓ Folder saved to: {dest}")


def _folder_via_zip(
    owner: str, repo: str, branch: str, folder: str, dest: Path
) -> None:
    """
    Fallback: download the full repo zip, extract only the requested subfolder.
    No API calls — works even when rate-limited.
    """
    locked_print("  Falling back to full-repo zip extraction …")
    zip_bytes = _download_zip(owner, repo, branch)

    zip_prefix = f"{repo}-{branch}/{folder.rstrip('/')}/"

    dest.mkdir(parents=True, exist_ok=True)

    extracted = 0
    with tempfile.TemporaryDirectory() as tmp:
        zip_path = Path(tmp) / "repo.zip"
        zip_path.write_bytes(zip_bytes)

        with zipfile.ZipFile(zip_path) as zf:
            members = [m for m in zf.namelist() if m.startswith(zip_prefix)
                       and not m.endswith("/")]
            if not members:
                raise FileNotFoundError(
                    f"Folder '{folder}' not found in the zip archive."
                )
            for member in members:
                rel_path  = member[len(zip_prefix):]
                file_dest = dest / rel_path
                file_dest.parent.mkdir(parents=True, exist_ok=True)
                file_dest.write_bytes(zf.read(member))
                locked_print(f"    ✓ {rel_path}")
                extracted += 1

    locked_print(f"\n✓ {extracted} file(s) saved to: {dest}")


def download_folder(
    owner: str, repo: str, branch: str, folder: str, dest: Path
) -> None:
    """
    Download only a subfolder. Tries the GitHub API first; if rate-limited
    or unauthenticated, falls back to downloading the full zip and extracting
    just the requested folder — no API quota consumed.
    """
    locked_print(f"Target folder : {folder}\n")
    try:
        _folder_via_api(owner, repo, branch, folder, dest)
    except urllib.error.HTTPError as exc:
        if exc.code in (403, 429):
            locked_print(
                f"  API rate limit hit (HTTP {exc.code}).\n"
                "  Tip: set GITHUB_TOKEN env var to increase your quota.\n"
                "  See script docstring for details.\n"
            )
            _folder_via_zip(owner, repo, branch, folder, dest)
        else:
            raise exc
    except FileNotFoundError:
        raise


# ══════════════════════════════════════════════════════════════════════════════
# add_games — markdown parsing, JS injection, game downloading
# ══════════════════════════════════════════════════════════════════════════════

def parse_js_games(js_text: str) -> tuple[list[str], int]:
    titles = re.findall(r'title:\s*"([^"]+)"', js_text)
    ids    = [int(m) for m in re.findall(r'\bid:\s*(\d+)', js_text)]
    return titles, (max(ids) if ids else 0)


def pick_url(urls: list[str]) -> tuple[str, str]:
    """
    Given a list of repo URLs, return (chosen_url, reason).
    Priority: bread's URL (contains BREAD_GITHUB) > last in list.
    """
    for url in urls:
        if BREAD_GITHUB in url:
            return url, f"bread's port ({url})"
    return urls[-1], f"highest-numbered port ({urls[-1]})"


def parse_md_games(md_text: str, debug: bool = False) -> list[dict]:
    """
    Parse each game line, handling both single and multiple port URLs.
    Returns list of {title, repo_url, porter, chosen_reason}.
    """
    games = []

    for line in md_text.splitlines():
        line = line.strip().replace("\u00a0", " ").replace("\u200b", "")
        if not line or not line.startswith("-"):
            continue

        if debug:
            locked_print(f"  [debug] raw : {repr(line)}")

        porter_match = re.search(r'[Pp]orts?(?:ed)?(?: by the| by) (.+)$', line)
        if not porter_match:
            if debug:
                locked_print("  [debug] match: None (no 'port by' found)")
            continue

        porter_section = porter_match.group(1)
        porter_names = re.findall(r'\[([^\]]+)\]\([^)]+\)', porter_section)

        title_match = re.search(r'-\s+\[(?P<title>[^\]]+)\]', line)
        if not title_match:
            if debug:
                locked_print("  [debug] match: None (no title found)")
            continue
        title = title_match.group("title")

        pre_porter = line[:porter_match.start()]
        repo_urls = re.findall(
            r'_*(?P<url>https://github\.com/[^_)\s]+?)_*\)',
            pre_porter
        )

        if not repo_urls:
            if debug:
                locked_print("  [debug] match: None (no github URLs found)")
            continue

        chosen_url, reason = pick_url(repo_urls)
        porter = ", ".join(porter_names) if porter_names else "unknown"

        if debug:
            locked_print(f"  [debug] title: {title}")
            locked_print(f"  [debug] urls : {repo_urls}")
            locked_print(f"  [debug] chose: {chosen_url} — {reason}")
            locked_print(f"  [debug] porter: {porter}")

        games.append({
            "title":          title,
            "repo_url":       chosen_url,
            "porter":         porter,
            "chosen_reason":  reason,
        })

    return games


def make_entry(game: dict, game_id: int) -> str:
    return (
        f"  {{\n"
        f'id: {game_id},\n'
        f'title: "{game["title"]}",\n'
        f'description: "By: {game["porter"]}",\n'
        f'thumbnail: "/thumbs/{game_id}.png",\n'
        f'url: "/games/{game_id}/index.html",\n'
        f"  }}"
    )


def inject_games(js_text: str, new_entries: list[str]) -> str:
    close = js_text.rfind("];")
    if close == -1:
        sys.exit("Could not find closing `];` in the JS file.")
    insert_block = ",\n".join(new_entries) + ",\n"
    return js_text[:close] + insert_block + js_text[close:]


def download_game(title: str, repo_url: str, game_id: int, games_dir: Path) -> bool:
    dest = games_dir / str(game_id)
    dest.mkdir(parents=True, exist_ok=True)

    try:
        info = parse_github_url(repo_url)

        owner  = info["owner"]
        repo   = info["repo"]
        branch = info["branch"] or default_branch(owner, repo)

        locked_print(f"  Owner: {owner}  Repo: {repo}  Branch: {branch}")

        if info["is_folder"]:
            download_folder(owner, repo, branch, info["folder"], dest)
        else:
            download_repo(owner, repo, branch, dest)

        return True

    except urllib.error.HTTPError as e:
        reason = "404 not found" if e.code == 404 else f"HTTP {e.code}"
        locked_print(f"  ⚠ Skipped ({reason})")
        log_failure(title, game_id, repo_url, reason)
    except FileNotFoundError as e:
        reason = f"no files found: {e}"
        locked_print(f"  ⚠ Skipped ({reason})")
        log_failure(title, game_id, repo_url, reason)
    except Exception as e:
        reason = f"error: {e}"
        locked_print(f"  ⚠ Skipped ({reason})")
        log_failure(title, game_id, repo_url, reason)

    try:
        if dest.exists() and not any(dest.iterdir()):
            dest.rmdir()
    except Exception:
        pass

    return False


def download_games_parallel(
    to_download: list[tuple[dict, int]],
    games_dir: Path,
    workers: int,
) -> dict[int, bool]:
    """
    Download multiple games concurrently.
    Returns a dict mapping game_id → success (bool).
    """
    results: dict[int, bool] = {}

    def _task(game: dict, game_id: int) -> tuple[int, bool]:
        locked_print(f"── Downloading \"{game['title']}\" (id {game_id}) ──")
        ok = download_game(game["title"], game["repo_url"], game_id, games_dir)
        locked_print(f"{'✓' if ok else '✗'} Finished \"{game['title']}\" (id {game_id})\n")
        return game_id, ok

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_task, game, gid): gid for game, gid in to_download}
        for future in as_completed(futures):
            gid, ok = future.result()
            results[gid] = ok

    return results


# ══════════════════════════════════════════════════════════════════════════════
# CLI entry points
# ══════════════════════════════════════════════════════════════════════════════

def cmd_download(argv: list[str]) -> None:
    """Handle the 'download' subcommand."""
    if not argv:
        print("Usage: game_manager.py download <github_url> [output_dir]")
        sys.exit(1)

    github_url = argv[0]
    dest       = Path(argv[1]) if len(argv) >= 2 else Path(".")
    dest.mkdir(parents=True, exist_ok=True)

    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token:
        print("ℹ Using GITHUB_TOKEN for authentication.")

    info   = parse_github_url(github_url)
    owner  = info["owner"]
    repo   = info["repo"]
    branch = info["branch"] or default_branch(owner, repo)

    print(f"Owner  : {owner}")
    print(f"Repo   : {repo}")
    print(f"Branch : {branch}")

    if info["is_folder"]:
        print(f"Folder : {info['folder']}")
        print()
        download_folder(owner, repo, branch, info["folder"], dest)
    else:
        print()
        download_repo(owner, repo, branch, dest)


def _parse_workers(argv: list[str], default: int = 4) -> int:
    """Extract --workers N from argv, returning the integer value."""
    for i, arg in enumerate(argv):
        if arg == "--workers" and i + 1 < len(argv):
            try:
                n = int(argv[i + 1])
                if n < 1:
                    raise ValueError
                return n
            except ValueError:
                sys.exit(f"--workers requires a positive integer, got: {argv[i + 1]!r}")
    return default


def cmd_add(argv: list[str]) -> None:
    """Handle the 'add' subcommand."""
    args    = [a for a in argv if not a.startswith("--")]
    debug   = "--debug" in argv
    workers = _parse_workers(argv)

    if len(args) < 2:
        print("Usage: game_manager.py add <games.js> <games.md> [games_dir] [--debug] [--workers N]")
        sys.exit(1)

    js_path   = Path(args[0])
    md_path   = Path(args[1])
    games_dir = Path(args[2]) if len(args) >= 3 else Path("games")

    if not js_path.exists():
        sys.exit(f"JS file not found: {js_path}")
    if not md_path.exists():
        sys.exit(f"MD file not found: {md_path}")

    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token:
        print("ℹ Using GITHUB_TOKEN for authentication.")

    js_text = js_path.read_text(encoding="utf-8")
    md_text = md_path.read_text(encoding="utf-8")

    existing_titles, max_id = parse_js_games(js_text)
    md_games = parse_md_games(md_text, debug=debug)

    if not md_games:
        print("No games found. Re-run with --debug to inspect each line, e.g.:")
        print(f"  python game_manager.py add {args[0]} {args[1]} --debug")
        sys.exit(1)

    new_entries = []
    to_download = []
    next_id = max_id + 1

    for game in md_games:
        if game["title"] in existing_titles:
            print(f"  skip  \"{game['title']}\" (already in JS)")
            continue
        new_entries.append(make_entry(game, next_id))
        to_download.append((game, next_id))
        print(f"  add   \"{game['title']}\" → id {next_id}  [{game['chosen_reason']}]")
        next_id += 1

    if not new_entries:
        print("Nothing to add.")
        return

    updated = inject_games(js_text, new_entries)
    js_path.write_text(updated, encoding="utf-8")
    print(f"\n✓ {len(new_entries)} game(s) added to {js_path}\n")

    print(f"Downloading {len(to_download)} game(s) with {workers} parallel worker(s) …\n")
    results = download_games_parallel(to_download, games_dir, workers)

    succeeded = sum(1 for ok in results.values() if ok)
    failed    = len(results) - succeeded
    print(f"✓ All done — {succeeded} succeeded, {failed} failed.")
    if failed:
        print(f"  See {FAILURE_LOG} for details.")


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0)

    subcommand = sys.argv[1]
    rest       = sys.argv[2:]

    if subcommand == "download":
        cmd_download(rest)
    elif subcommand == "add":
        cmd_add(rest)
    else:
        print(f"Unknown subcommand: '{subcommand}'")
        print("Use 'download' or 'add'. Run with --help for usage.")
        sys.exit(1)


if __name__ == "__main__":
    main()