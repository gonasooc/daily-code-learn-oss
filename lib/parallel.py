"""저장소 병렬 처리 공용 헬퍼."""

import os
from concurrent.futures import ThreadPoolExecutor, as_completed

from lib.scanner import get_path_identity, scan_repos
from lib.progress import ProgressDisplay

MAX_WORKERS = min(8, os.cpu_count() or 4)


class ParallelResults(list):
    """List-compatible results with per-repository failures attached."""

    def __init__(self, values=(), errors=None):
        super().__init__(values)
        self.errors = errors or []


class RepoTasks(list):
    """Repository tasks plus root-level discovery failures."""

    def __init__(self, values=(), errors=None):
        super().__init__(values)
        self.errors = errors or []


def get_repo_relative_path(repo_path, root):
    """Return a stable, user-facing repository path relative to its root."""
    root_path = root.get("path", "")
    try:
        relative_path = os.path.relpath(repo_path, root_path)
    except (OSError, TypeError, ValueError):
        relative_path = os.path.basename(os.path.normpath(repo_path))

    if relative_path == ".":
        relative_path = os.path.basename(os.path.normpath(repo_path)) or "."
    return relative_path.replace(os.sep, "/")


def collect_repo_tasks(config):
    """config의 모든 root에서 저장소 목록을 수집한다.

    Returns:
        list of (repo_path, root) tuples
    """
    tasks = []
    errors = []
    seen_repositories = {}
    for root in config.get("roots", []):
        root_path = root["path"]
        max_depth = root.get("maxDepth", 1)
        if not os.path.isdir(root_path):
            errors.append({
                "repo_path": root_path,
                "repo_relative_path": get_repo_relative_path(root_path, root),
                "root_name": root.get("name", "(unknown)"),
                "message": "저장소 탐색 실패: root 경로가 없습니다.",
            })
            continue
        try:
            repo_paths = scan_repos(root_path, max_depth=max_depth)
        except Exception as error:
            errors.append({
                "repo_path": root_path,
                "repo_relative_path": get_repo_relative_path(root_path, root),
                "root_name": root.get("name", "(unknown)"),
                "message": f"저장소 탐색 실패: {error}",
            })
            continue
        for repo_path in repo_paths:
            try:
                repository_identity = get_path_identity(repo_path)
            except OSError as error:
                errors.append({
                    "repo_path": repo_path,
                    "repo_relative_path": get_repo_relative_path(
                        repo_path,
                        root,
                    ),
                    "root_name": root.get("name", "(unknown)"),
                    "message": f"저장소 정체성 확인 실패: {error}",
                })
                continue
            previous = seen_repositories.get(repository_identity)
            if previous is not None:
                previous_path, previous_root = previous
                errors.append({
                    "repo_path": repo_path,
                    "repo_relative_path": get_repo_relative_path(repo_path, root),
                    "root_name": root.get("name", "(unknown)"),
                    "message": (
                        "동일한 저장소가 여러 root에서 발견되었습니다: "
                        f"[{previous_root.get('name', '(unknown)')}] "
                        f"{get_repo_relative_path(previous_path, previous_root)}"
                    ),
                })
                continue
            seen_repositories[repository_identity] = (repo_path, root)
            tasks.append((repo_path, root))
    return RepoTasks(tasks, errors=errors)


def run_parallel_over_repos(config, process_fn):
    """config의 모든 저장소에 대해 process_fn을 병렬로 실행한다.

    Args:
        config: 설정 딕셔너리
        process_fn: (repo_path, root, progress) -> result 또는 None

    Returns:
        list of non-None results
    """
    tasks = collect_repo_tasks(config)
    if not tasks:
        return ParallelResults(errors=getattr(tasks, "errors", []))

    progress = ProgressDisplay(len(tasks))
    results = []
    errors = list(getattr(tasks, "errors", []))

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(process_fn, repo_path, root, progress): (repo_path, root)
            for repo_path, root in tasks
        }

        for future in as_completed(futures):
            repo_path, root = futures[future]
            try:
                result = future.result()
            except Exception as error:
                progress.complete_one()
                errors.append({
                    "repo_path": repo_path,
                    "repo_relative_path": get_repo_relative_path(repo_path, root),
                    "root_name": root.get("name", "(unknown)"),
                    "message": str(error),
                })
                continue
            if result is not None:
                results.append(result)

    progress.finish()
    return ParallelResults(results, errors=errors)
