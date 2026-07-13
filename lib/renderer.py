import fcntl
import hashlib
import os
import re
import secrets
import stat
from contextlib import contextmanager

from lib.colors import safe_multiline_text, safe_terminal_text


MAX_READABLE_FILENAME_LENGTH = 160


class WrittenReportPath(str):
    """A path string carrying the identity of the artifact just written.

    Keeping this as a ``str`` subclass preserves the existing public return
    value while allowing the notifier to reject a directory or file that was
    replaced between report generation and delivery.
    """

    def __new__(
        cls,
        path,
        *,
        directory_identity,
        file_identity,
        content_sha256,
    ):
        instance = super().__new__(cls, path)
        instance.report_directory_identity = directory_identity
        instance.report_file_identity = file_identity
        instance.report_content_sha256 = content_sha256
        return instance


def _report_identity(report):
    root_name = report.get("root_name", "workspace")
    relative_path = report.get("repo_relative_path", report["project_name"])
    relative_path = str(relative_path)
    return root_name, relative_path, f"{root_name}/{relative_path}"


def _report_identity_digest(report):
    root_name, relative_path, _display_name = _report_identity(report)
    root_bytes = str(root_name).encode("utf-8", errors="surrogatepass")
    relative_bytes = relative_path.encode("utf-8", errors="surrogatepass")
    identity_bytes = (
        len(root_bytes).to_bytes(8, byteorder="big")
        + root_bytes
        + relative_bytes
    )
    return hashlib.sha256(identity_bytes).hexdigest()


def _display_text(value):
    """Return single-line, valid UTF-8 text for generated Markdown."""
    return safe_terminal_text(value)


def _display_diff_text(value):
    """Keep diff line structure while neutralizing terminal controls."""
    return safe_multiline_text(value)


def _escape_markdown_text(value):
    text = _display_text(value).replace("\\", "\\\\")
    return re.sub(r"([`*_\[\]<>#])", r"\\\1", text)


def _inline_code(value):
    text = _display_text(value)
    longest_run = max(
        (len(match.group(0)) for match in re.finditer(r"`+", text)),
        default=0,
    )
    fence = "`" * max(1, longest_run + 1)
    if "`" in text or text.startswith(" ") or text.endswith(" "):
        return f"{fence} {text} {fence}"
    return f"{fence}{text}{fence}"


def build_report_filename(report):
    """Build a deterministic, collision-resistant report filename."""
    root_name, relative_path, _display_name = _report_identity(report)
    readable = f"{root_name}--{relative_path.replace('/', '--')}"
    readable = re.sub(r"[^A-Za-z0-9._-]+", "-", readable).strip("-._")
    if not readable:
        readable = "repository"
    readable = readable[:MAX_READABLE_FILENAME_LENGTH].rstrip("-._")
    digest = _report_identity_digest(report)[:16]
    return f"{readable}--{digest}.md"


def render_markdown(report, date):
    """리포트 딕셔너리를 마크다운 문자열로 변환한다."""
    lines = []
    root_name, relative_path, display_name = _report_identity(report)

    lines.append(f"# {date} - {_escape_markdown_text(display_name)}")
    lines.append(
        f"<!-- daily-code-learn-report:v1:{_report_identity_digest(report)} -->"
    )
    lines.append("")

    # 기본 정보
    lines.append("## 기본 정보")
    lines.append(f"- 저장소: {_inline_code(f'{root_name}/{relative_path}')}")
    lines.append(f"- 브랜치: {_inline_code(report['branch'])}")
    author_names = report.get("author_names")
    if author_names is None and report.get("author_name"):
        author_names = [report["author_name"]]
    lines.append(
        f"- 작성자: {_escape_markdown_text(', '.join(author_names or []))}"
    )
    lines.append("")

    _append_work_summary(lines, report)

    # 커밋
    if report["commits"]:
        lines.append("## 대상 날짜 커밋")
        for commit in report["commits"]:
            lines.append(f"### {_escape_markdown_text(commit['subject'])}")
            lines.append(f"- Hash: {_inline_code(commit['hash'][:7])}")
            time_part = _extract_time(commit["date"])
            lines.append(f"- 시간: {time_part}")
            lines.append(f"- 변경: {commit['files_changed']} files (+{commit['insertions']} -{commit['deletions']})")
            if commit.get("diff_truncated"):
                omitted = commit.get("diff_omitted_lines", 0)
                if omitted is None:
                    lines.append("- Diff: 설정된 크기 또는 줄 수 제한 이후 생략")
                else:
                    lines.append(f"- Diff: 일부 diff 생략 ({omitted}줄)")

            if commit.get("diff"):
                _append_diff_details(lines, "diff 보기", commit["diff"])

            lines.append("")

    # 현재 작업 중 변경
    has_staged = bool(report["staged_files"])
    has_unstaged = bool(report["unstaged_files"])
    has_untracked = bool(report.get("untracked_files", []))

    if has_staged or has_unstaged or has_untracked:
        lines.append("## 현재 작업 중 변경")

        if has_staged:
            _append_uncommitted_change(
                lines,
                "Staged",
                report["staged_files"],
                report.get("staged_diff", ""),
                report.get("include_uncommitted_diff", True),
                report.get("staged_diff_truncated", False),
                report.get("staged_diff_omitted_lines", 0),
            )

        if has_unstaged:
            _append_uncommitted_change(
                lines,
                "Unstaged",
                report["unstaged_files"],
                report.get("unstaged_diff", ""),
                report.get("include_uncommitted_diff", True),
                report.get("unstaged_diff_truncated", False),
                report.get("unstaged_diff_omitted_lines", 0),
            )

        if has_untracked:
            _append_file_list(lines, "Untracked", report.get("untracked_files", []))

    return "\n".join(lines)


def _append_work_summary(lines, report):
    """리포트 상단에 프로젝트 단위 작업량 요약을 추가한다."""
    commits = report["commits"]
    staged_files = report["staged_files"]
    unstaged_files = report["unstaged_files"]
    untracked_files = report.get("untracked_files", [])
    commit_files = sum(commit.get("files_changed", 0) for commit in commits)
    insertions = sum(commit.get("insertions", 0) for commit in commits)
    deletions = sum(commit.get("deletions", 0) for commit in commits)

    lines.append("## 작업 요약")
    lines.append(f"- 커밋: {len(commits)}건")
    lines.append(f"- 커밋 변경량: {commit_files} files (+{insertions} -{deletions})")
    lines.append(f"- Staged: {len(staged_files)} files")
    lines.append(f"- Unstaged: {len(unstaged_files)} files")
    lines.append(f"- Untracked: {len(untracked_files)} files")
    lines.append("")


def _append_diff_details(lines, summary, diff):
    """diff를 details 코드블록으로 추가한다."""
    diff = _display_diff_text(diff)
    lines.append("")
    lines.append("<details>")
    lines.append(f"<summary>{summary}</summary>")
    lines.append("")
    longest_run = max((len(match.group(0)) for match in re.finditer(r"`+", diff)), default=0)
    fence = "`" * max(3, longest_run + 1)
    lines.append(f"{fence}diff")
    lines.append(diff)
    lines.append(fence)
    lines.append("")
    lines.append("</details>")


def _append_uncommitted_change(lines, title, files, diff, include_diff, truncated, omitted_lines):
    """staged/unstaged 변경 목록과 diff를 추가한다."""
    lines.append(f"### {title}")
    for f in files:
        lines.append(f"- {_inline_code(f)}")

    if not include_diff:
        lines.append("- diff: 설정에서 비활성화됨")
        lines.append("")
        return

    if truncated:
        if omitted_lines is None:
            lines.append("- Diff: 설정된 크기 또는 줄 수 제한 이후 생략")
        else:
            lines.append(f"- Diff: 일부 diff 생략 ({omitted_lines}줄)")

    if diff:
        _append_diff_details(lines, f"{title.lower()} diff 보기", diff)

    lines.append("")


def _append_file_list(lines, title, files):
    """diff 없이 파일 목록만 추가한다."""
    lines.append(f"### {title}")
    for f in files:
        lines.append(f"- {_inline_code(f)}")
    lines.append("")


def _extract_time(date_str):
    """ISO 날짜 문자열에서 HH:mm을 추출한다."""
    try:
        # "2026-03-12 14:30:00 +0900" 형태
        parts = date_str.strip().split(" ")
        if len(parts) >= 2:
            time_parts = parts[1].split(":")
            return f"{time_parts[0]}:{time_parts[1]}"
    except (AttributeError, IndexError, TypeError, ValueError):
        pass
    return date_str


def write_report(report, date, output_dir):
    """Safely publish a Markdown report with private file permissions."""
    dir_path = os.path.join(output_dir, date)
    missing_output_directories = _missing_directory_paths(output_dir)
    os.makedirs(output_dir, exist_ok=True)
    for created_path in reversed(missing_output_directories):
        _fsync_directory_path(os.path.dirname(created_path))
    date_directory_created = False
    try:
        os.mkdir(dir_path, mode=0o700)
    except FileExistsError:
        pass
    else:
        date_directory_created = True
    if date_directory_created:
        _fsync_directory_path(output_dir)

    file_name = build_report_filename(report)
    file_path = os.path.join(dir_path, file_name)
    content = render_markdown(report, date)
    content_bytes = content.encode("utf-8")
    content_sha256 = hashlib.sha256(content_bytes).hexdigest()
    with _directory_lock(dir_path) as directory_fd:
        _ensure_no_recovery_artifacts(directory_fd, dir_path)
        existing_identity = _ensure_replaceable_report(
            directory_fd,
            file_name,
            file_path,
            content,
        )

        file_descriptor, temporary_name = _create_temporary_report(directory_fd)
        try:
            with os.fdopen(file_descriptor, "wb") as file:
                file.write(content_bytes)
                file.flush()
                os.fsync(file.fileno())
                temporary_info = os.fstat(file.fileno())
                temporary_identity = (
                    temporary_info.st_dev,
                    temporary_info.st_ino,
                )
            _assert_directory_path(dir_path, directory_fd)
            previous_name = _publish_temporary_report(
                directory_fd,
                temporary_name,
                file_name,
                file_path,
                existing_identity,
            )
            os.fsync(directory_fd)
            _assert_directory_path(dir_path, directory_fd)
            file_identity = _verify_published_report(
                directory_fd,
                file_name,
                file_path,
                temporary_identity,
                content_sha256,
            )
            if previous_name is not None:
                os.unlink(previous_name, dir_fd=directory_fd)
                os.fsync(directory_fd)
            directory_info = os.fstat(directory_fd)
            directory_identity = (
                directory_info.st_dev,
                directory_info.st_ino,
            )
        except BaseException:
            try:
                os.unlink(temporary_name, dir_fd=directory_fd)
            except OSError:
                pass
            raise

    return WrittenReportPath(
        file_path,
        directory_identity=directory_identity,
        file_identity=file_identity,
        content_sha256=content_sha256,
    )


@contextmanager
def _directory_lock(dir_path):
    """Serialize cooperating report writers for one date directory."""
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    directory_fd = os.open(dir_path, flags)
    locked = False
    try:
        directory_info = os.fstat(directory_fd)
        _validate_report_directory_info(directory_info, dir_path)
        fcntl.flock(directory_fd, fcntl.LOCK_EX)
        locked = True
        # Permission bits can change while this process waits for another
        # cooperating writer. Recheck only after the lock is actually held.
        _validate_report_directory_info(os.fstat(directory_fd), dir_path)
        yield directory_fd
    finally:
        try:
            if locked:
                fcntl.flock(directory_fd, fcntl.LOCK_UN)
        finally:
            os.close(directory_fd)


def _validate_report_directory_info(directory_info, dir_path):
    if not stat.S_ISDIR(directory_info.st_mode):
        raise NotADirectoryError(
            f"날짜별 리포트 경로가 디렉터리가 아닙니다: {dir_path}"
        )
    if directory_info.st_uid != os.geteuid():
        raise PermissionError(
            f"날짜별 리포트 디렉터리의 소유자가 현재 사용자와 다릅니다: {dir_path}"
        )
    if stat.S_IMODE(directory_info.st_mode) & 0o022:
        raise PermissionError(
            f"날짜별 리포트 디렉터리에 그룹/기타 쓰기 권한이 있습니다: {dir_path}"
        )


def _missing_directory_paths(path):
    """Return missing ancestors from the requested path toward an existing one."""
    missing = []
    current = os.path.abspath(path)
    while not os.path.exists(current):
        missing.append(current)
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    return missing


def _fsync_directory_path(path):
    """Persist directory entries created in a named parent directory."""
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    directory_fd = os.open(path or os.curdir, flags)
    try:
        if not stat.S_ISDIR(os.fstat(directory_fd).st_mode):
            raise NotADirectoryError(path)
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _ensure_no_recovery_artifacts(directory_fd, dir_path):
    """Stop before creating more artifacts when a prior write was interrupted."""
    recovery_pattern = re.compile(
        r"\.(?:report|previous-report)-[0-9a-f]{24}\.tmp"
    )
    recovery_names = sorted(
        name
        for name in os.listdir(directory_fd)
        if recovery_pattern.fullmatch(name)
    )
    if recovery_names:
        raise FileExistsError(
            "이전 리포트 게시가 중단된 복구 파일이 있습니다. 내용을 검토한 "
            f"뒤 수동으로 정리하세요: {dir_path}/{recovery_names[0]}"
        )


def _assert_directory_path(dir_path, directory_fd):
    """Ensure the displayed date path still names the locked directory."""
    try:
        path_info = os.stat(dir_path, follow_symlinks=False)
    except OSError as error:
        raise OSError(
            f"날짜별 리포트 디렉터리가 실행 중 변경되었습니다: {dir_path}"
        ) from error
    descriptor_info = os.fstat(directory_fd)
    if (
        not stat.S_ISDIR(path_info.st_mode)
        or path_info.st_dev != descriptor_info.st_dev
        or path_info.st_ino != descriptor_info.st_ino
    ):
        raise OSError(
            f"날짜별 리포트 디렉터리가 실행 중 변경되었습니다: {dir_path}"
        )


def _create_temporary_report(directory_fd):
    """Create an owner-only temporary file inside an already opened directory."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_CLOEXEC", 0)
    for _attempt in range(100):
        temporary_name = f".report-{secrets.token_hex(12)}.tmp"
        try:
            file_descriptor = os.open(
                temporary_name,
                flags,
                0o600,
                dir_fd=directory_fd,
            )
        except FileExistsError:
            continue
        try:
            os.fchmod(file_descriptor, 0o600)
        except OSError:
            os.close(file_descriptor)
            try:
                os.unlink(temporary_name, dir_fd=directory_fd)
            except OSError:
                pass
            raise
        return file_descriptor, temporary_name
    raise FileExistsError("임시 리포트 파일 이름을 만들 수 없습니다.")


def _ensure_replaceable_report(
    directory_fd,
    file_name,
    file_path,
    new_content,
):
    """Refuse to replace a file not owned by this report identity."""
    expected_lines = new_content.split("\n", 2)[:2]
    flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        file_descriptor = os.open(file_name, flags, dir_fd=directory_fd)
    except FileNotFoundError:
        return None
    except OSError as error:
        raise FileExistsError(
            f"기존 리포트 파일을 안전하게 확인할 수 없습니다: {file_path}: {error}"
        ) from error

    try:
        file_info = os.fstat(file_descriptor)
        if not stat.S_ISREG(file_info.st_mode):
            raise FileExistsError(
                f"기존 리포트 경로가 일반 파일이 아닙니다: {file_path}"
            )
        with os.fdopen(file_descriptor, "r", encoding="utf-8") as existing_file:
            file_descriptor = None
            observed_lines = [
                existing_file.readline(len(expected_line) + 2).rstrip("\n")
                for expected_line in expected_lines
            ]
    except FileExistsError:
        raise
    except (OSError, UnicodeError) as error:
        raise FileExistsError(
            f"기존 리포트 파일을 읽을 수 없습니다: {file_path}: {error}"
        ) from error
    finally:
        if file_descriptor is not None:
            os.close(file_descriptor)

    if observed_lines != expected_lines:
        raise FileExistsError(
            f"기존 파일이 같은 저장소의 생성 리포트가 아닙니다: {file_path}"
        )

    return file_info.st_dev, file_info.st_ino


def _publish_temporary_report(
    directory_fd,
    temporary_name,
    file_name,
    file_path,
    existing_identity,
):
    """Publish a new report exclusively or retain an owned previous inode.

    New files use an exclusive hard-link publication. For an existing report,
    a hard-link backup is created and both names are revalidated before the
    atomic replacement. The caller removes the backup only after validating
    and syncing the newly published bytes.
    """
    if existing_identity is None:
        try:
            os.link(
                temporary_name,
                file_name,
                src_dir_fd=directory_fd,
                dst_dir_fd=directory_fd,
                follow_symlinks=False,
            )
        except FileExistsError as error:
            raise FileExistsError(
                "리포트 파일이 검사 후 다른 항목으로 생성되었습니다: "
                f"{file_path}"
            ) from error
        except OSError as error:
            raise OSError(
                "리포트 파일을 안전하게 게시할 수 없습니다. outputDir의 "
                f"파일시스템이 동일 디렉터리 하드 링크를 지원해야 합니다: {error}"
            ) from error
        os.unlink(temporary_name, dir_fd=directory_fd)
        return None

    previous_name = _create_previous_report_link(
        directory_fd,
        file_name,
    )
    replacement_attempted = False
    try:
        previous_info = os.stat(
            previous_name,
            dir_fd=directory_fd,
            follow_symlinks=False,
        )
        previous_identity = (
            previous_info.st_dev,
            previous_info.st_ino,
        )
        if (
            not stat.S_ISREG(previous_info.st_mode)
            or previous_identity != existing_identity
        ):
            raise FileExistsError(
                "리포트 파일이 검사 후 다른 항목으로 교체되었습니다: "
                f"{file_path}"
            )
        os.fsync(directory_fd)
        current_info = os.stat(
            file_name,
            dir_fd=directory_fd,
            follow_symlinks=False,
        )
        if (
            not stat.S_ISREG(current_info.st_mode)
            or (current_info.st_dev, current_info.st_ino)
            != existing_identity
        ):
            raise FileExistsError(
                "리포트 파일이 갱신 직전에 다른 항목으로 교체되었습니다: "
                f"{file_path}"
            )
        replacement_attempted = True
        os.replace(
            temporary_name,
            file_name,
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
        )
        return previous_name
    except BaseException:
        if not replacement_attempted:
            try:
                os.unlink(previous_name, dir_fd=directory_fd)
            except OSError:
                pass
        raise


def _create_previous_report_link(directory_fd, file_name):
    """Retain the current target inode under an unpredictable private name."""
    for _attempt in range(100):
        previous_name = f".previous-report-{secrets.token_hex(12)}.tmp"
        try:
            os.link(
                file_name,
                previous_name,
                src_dir_fd=directory_fd,
                dst_dir_fd=directory_fd,
                follow_symlinks=False,
            )
        except FileExistsError:
            continue
        except OSError as error:
            raise OSError(
                "기존 리포트를 안전하게 보존할 수 없습니다. outputDir의 "
                f"파일시스템이 동일 디렉터리 하드 링크를 지원해야 합니다: {error}"
            ) from error
        return previous_name
    raise FileExistsError("이전 리포트 보존 이름을 만들 수 없습니다.")


def _verify_published_report(
    directory_fd,
    file_name,
    file_path,
    expected_identity,
    expected_sha256,
):
    """Bind the returned artifact metadata to the bytes now at the target."""
    flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    file_descriptor = os.open(file_name, flags, dir_fd=directory_fd)
    try:
        file_info = os.fstat(file_descriptor)
        observed_identity = (file_info.st_dev, file_info.st_ino)
        if (
            not stat.S_ISREG(file_info.st_mode)
            or observed_identity != expected_identity
        ):
            raise OSError(
                f"게시된 리포트 파일이 실행 중 변경되었습니다: {file_path}"
            )
        digest = hashlib.sha256()
        while True:
            chunk = os.read(file_descriptor, 64 * 1024)
            if not chunk:
                break
            digest.update(chunk)
        if digest.hexdigest() != expected_sha256:
            raise OSError(
                f"게시된 리포트 내용이 실행 중 변경되었습니다: {file_path}"
            )
        return observed_identity
    finally:
        os.close(file_descriptor)
