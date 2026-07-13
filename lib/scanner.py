import os


def get_path_identity(path):
    """Return a filesystem identity that survives aliases and path casing."""
    info = os.stat(path, follow_symlinks=True)
    return info.st_dev, info.st_ino


def get_directory_ancestor_identities(path):
    """Return identities for a directory and every resolved ancestor."""
    identities = set()
    current = os.path.realpath(os.path.abspath(path))
    while True:
        identities.add(get_path_identity(current))
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    return identities


def _is_git_repo(path):
    """Recognize regular repositories and linked worktrees."""
    git_entry = os.path.join(path, ".git")
    return os.path.isdir(git_entry) or os.path.isfile(git_entry)


def scan_repos(root_path, max_depth=1):
    """Return repositories under root_path up to max_depth levels deep.

    Depth 1 means direct children, preserving the original behavior. Once a
    repository is found its contents are not traversed, which prevents nested
    dependencies from being treated as workspace repositories.
    """
    repos = []
    if not os.path.isdir(root_path) or max_depth < 1:
        return repos

    root_path = os.path.abspath(root_path)
    if _is_git_repo(root_path):
        return [root_path]

    def _raise_walk_error(error):
        raise error

    for current_path, dir_names, _file_names in os.walk(
        root_path,
        onerror=_raise_walk_error,
    ):
        relative = os.path.relpath(current_path, root_path)
        current_depth = 0 if relative == "." else len(relative.split(os.sep))

        if current_depth >= max_depth:
            dir_names[:] = []
            continue

        kept_dirs = []
        for name in sorted(dir_names):
            if name == ".git":
                continue
            full_path = os.path.join(current_path, name)
            if _is_git_repo(full_path):
                repos.append(full_path)
            else:
                kept_dirs.append(name)
        dir_names[:] = kept_dirs

    unique_repos = {}
    ordered_repos = sorted(
        set(repos),
        key=lambda path: (
            os.path.normcase(os.path.abspath(path))
            != os.path.normcase(os.path.realpath(path)),
            path,
        ),
    )
    for repo_path in ordered_repos:
        identity = get_path_identity(repo_path)
        unique_repos.setdefault(identity, repo_path)
    return list(unique_repos.values())
