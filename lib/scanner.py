import os


def scan_repos(root_path):
    """root_path 하위의 git 저장소 경로 목록을 반환한다."""
    repos = []
    if not os.path.isdir(root_path):
        return repos

    for name in sorted(os.listdir(root_path)):
        full_path = os.path.join(root_path, name)
        if os.path.isdir(full_path) and os.path.isdir(os.path.join(full_path, ".git")):
            repos.append(full_path)

    return repos
