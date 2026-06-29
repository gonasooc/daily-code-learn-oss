"""저장소 병렬 처리 공용 헬퍼."""

import os
from concurrent.futures import ThreadPoolExecutor, as_completed

from lib.scanner import scan_repos
from lib.progress import ProgressDisplay

MAX_WORKERS = min(8, os.cpu_count() or 4)


def collect_repo_tasks(config):
    """config의 모든 root에서 저장소 목록을 수집한다.

    Returns:
        list of (repo_path, root) tuples
    """
    tasks = []
    for root in config.get("roots", []):
        root_path = root["path"]
        for repo_path in scan_repos(root_path):
            tasks.append((repo_path, root))
    return tasks


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
        return []

    progress = ProgressDisplay(len(tasks))
    results = []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(process_fn, repo_path, root, progress): (repo_path, root)
            for repo_path, root in tasks
        }

        for future in as_completed(futures):
            result = future.result()
            if result is not None:
                results.append(result)

    progress.finish()
    return results
