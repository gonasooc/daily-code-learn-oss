import argparse
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from datetime import datetime

from lib import __version__
from lib.colors import red, yellow, dim, green, cyan, safe_terminal_text
from lib.git_commands import GitCommandError, validate_worktree
from lib.scanner import (
    get_directory_ancestor_identities,
    get_path_identity,
    scan_repos,
)

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "profiles.json")
EXAMPLE_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "profiles.example.json")
PROJECT_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
MIN_GIT_VERSION = (2, 37, 0)
MIN_GIT_VERSION_TEXT = ".".join(str(part) for part in MIN_GIT_VERSION)
MAX_MISSED_DAYS = 3650


def _load_env():
    """Load an owner-only regular .env file without following a symlink."""
    env_path = os.path.join(PROJECT_ROOT, ".env")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    try:
        file_descriptor = os.open(env_path, flags)
    except FileNotFoundError:
        return
    except OSError as error:
        raise ConfigError(f"환경 파일을 안전하게 열 수 없습니다: {env_path}: {error}") from error

    try:
        file_info = os.fstat(file_descriptor)
        if not stat.S_ISREG(file_info.st_mode):
            raise ConfigError(f"환경 파일이 일반 파일이 아닙니다: {env_path}")
        if file_info.st_uid != os.geteuid():
            raise ConfigError(
                f"환경 파일의 소유자가 현재 사용자와 다릅니다: {env_path}"
            )
        if stat.S_IMODE(file_info.st_mode) & 0o077:
            raise ConfigError(
                "환경 파일에 그룹/기타 사용자 권한이 있습니다. "
                f"chmod 600 {env_path} 를 실행하세요."
            )

        with os.fdopen(file_descriptor, "r", encoding="utf-8") as f:
            file_descriptor = None
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip()
                if key:
                    os.environ.setdefault(key, value)
    except ConfigError:
        raise
    except (OSError, UnicodeError, ValueError) as e:
        raise ConfigError(f"환경 파일 읽기 실패: {env_path}: {e}") from e
    finally:
        if file_descriptor is not None:
            os.close(file_descriptor)


PLACEHOLDER_EMAILS = {"me@example.com", "your@email.com", "you@example.com"}
PLACEHOLDER_NAMES = {"Your Name", "My Name"}


class ConfigError(Exception):
    """설정 파일을 읽을 수 없을 때 발생하는 사용자 표시용 오류."""


def _read_config_file(config_path):
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        raise ConfigError(
            f"설정 JSON 파싱 실패: {e.msg} "
            f"(라인 {e.lineno}, 열 {e.colno})"
        ) from e
    except (OSError, UnicodeError) as e:
        raise ConfigError(f"설정 파일 읽기 실패: {config_path}: {e}") from e


def _output_dir_error(output_dir):
    """outputDir에 필요한 읽기·쓰기·탐색 권한이 없으면 오류를 반환한다."""
    absolute_path = os.path.abspath(output_dir)

    if os.path.exists(absolute_path):
        if not os.path.isdir(absolute_path):
            return f"outputDir가 디렉터리가 아닙니다: {output_dir}"
        if not os.access(absolute_path, os.R_OK | os.W_OK | os.X_OK):
            return f"outputDir에 읽기·쓰기·탐색 권한이 없습니다: {output_dir}"
        return None

    parent = os.path.dirname(absolute_path)
    while not os.path.exists(parent):
        next_parent = os.path.dirname(parent)
        if next_parent == parent:
            break
        parent = next_parent

    if not os.path.isdir(parent) or not os.access(parent, os.W_OK | os.X_OK):
        return f"outputDir을 생성할 수 없습니다: {output_dir}"
    return None


def _validate_nonempty_string_list(value, field_name, label):
    if not isinstance(value, list) or not value:
        return f"[{label}] {field_name}는 비어 있지 않은 문자열 목록이어야 합니다."
    if any(not isinstance(item, str) or not item.strip() for item in value):
        return f"[{label}] {field_name}는 비어 있지 않은 문자열 목록이어야 합니다."
    return None


def validate_config(config):
    """실행과 doctor가 공유하는 설정 검증 오류 목록을 반환한다."""
    if not isinstance(config, dict):
        return ["설정의 최상위 값은 JSON 객체여야 합니다."]

    errors = []
    roots = config.get("roots")
    if not isinstance(roots, list):
        errors.append("roots는 비어 있지 않은 객체 목록이어야 합니다.")
    elif not roots:
        errors.append("roots 설정 없음: 하나 이상의 root가 필요합니다.")
    else:
        seen_names = set()
        seen_paths = []
        for index, root in enumerate(roots, start=1):
            fallback_label = f"root #{index}"
            if not isinstance(root, dict):
                errors.append(f"[{fallback_label}] root는 JSON 객체여야 합니다.")
                continue

            name = root.get("name")
            if not isinstance(name, str) or not name.strip():
                errors.append(
                    f"[{fallback_label}] name은 비어 있지 않은 문자열이어야 합니다."
                )
                label = fallback_label
            else:
                label = name.strip()
                if label in seen_names:
                    errors.append(f"[{label}] root name은 중복될 수 없습니다.")
                seen_names.add(label)

            root_path = root.get("path")
            if not isinstance(root_path, str) or not root_path.strip():
                errors.append(f"[{label}] path는 비어 있지 않은 문자열이어야 합니다.")
            elif not os.path.isdir(root_path):
                errors.append(f"[{label}] root 경로 없음: {root_path}")
            else:
                try:
                    root_identity = get_path_identity(root_path)
                    ancestor_identities = get_directory_ancestor_identities(
                        root_path
                    )
                except OSError as error:
                    errors.append(
                        f"[{label}] root 경로 확인 실패: {root_path}: {error}"
                    )
                else:
                    for (
                        previous_label,
                        previous_identity,
                        previous_ancestors,
                    ) in seen_paths:
                        if (
                            root_identity in previous_ancestors
                            or previous_identity in ancestor_identities
                        ):
                            errors.append(
                                f"[{label}] root 경로가 [{previous_label}]과 "
                                f"중복되거나 겹칩니다: {root_path}"
                            )
                            break
                    seen_paths.append((
                        label,
                        root_identity,
                        ancestor_identities,
                    ))

            if "maxDepth" in root:
                max_depth = root["maxDepth"]
                if (
                    not isinstance(max_depth, int)
                    or isinstance(max_depth, bool)
                    or max_depth < 1
                ):
                    errors.append(f"[{label}] maxDepth는 1 이상의 정수여야 합니다.")

            for field_name in ("authorNames", "authorEmails"):
                error = _validate_nonempty_string_list(
                    root.get(field_name), field_name, label
                )
                if error:
                    errors.append(error)

    output_dir = config.get("outputDir", "./reports")
    if not isinstance(output_dir, str) or not output_dir.strip():
        errors.append("outputDir은 비어 있지 않은 문자열이어야 합니다.")
    else:
        error = _output_dir_error(output_dir)
        if error:
            errors.append(error)

    report = config.get("report", {})
    if not isinstance(report, dict):
        errors.append("report는 JSON 객체여야 합니다.")
    else:
        for field_name in ("includeUncommittedDiff", "includeSensitiveFiles"):
            if field_name in report and not isinstance(report[field_name], bool):
                errors.append(f"report.{field_name}는 boolean이어야 합니다.")

        if "maxDiffLines" in report:
            max_diff_lines = report["maxDiffLines"]
            if (
                not isinstance(max_diff_lines, int)
                or isinstance(max_diff_lines, bool)
                or max_diff_lines < 0
            ):
                errors.append(
                    "report.maxDiffLines는 0 이상의 정수여야 합니다. "
                    "(0은 줄 제한 없음)"
                )

        if "maxDiffBytes" in report:
            max_diff_bytes = report["maxDiffBytes"]
            if (
                not isinstance(max_diff_bytes, int)
                or isinstance(max_diff_bytes, bool)
                or max_diff_bytes < 0
            ):
                errors.append(
                    "report.maxDiffBytes는 0 이상의 정수여야 합니다. "
                    "(0은 byte 제한 없음)"
                )

    exclude = config.get("exclude", [])
    if not isinstance(exclude, list) or any(
        not isinstance(item, str) for item in exclude
    ):
        errors.append("exclude는 문자열 목록이어야 합니다.")

    telegram = config.get("telegram", {}) if isinstance(config, dict) else {}
    if not isinstance(telegram, dict):
        errors.append("telegram은 JSON 객체여야 합니다.")
    elif "enabled" in telegram and not isinstance(telegram["enabled"], bool):
        errors.append("telegram.enabled는 boolean이어야 합니다.")

    return errors


def init_config():
    """예시 설정 파일을 실제 설정 파일로 복사한다."""
    config_path = os.path.normpath(CONFIG_PATH)
    example_path = os.path.normpath(EXAMPLE_PATH)

    if os.path.exists(config_path):
        print(yellow(
            "이미 설정 파일이 있습니다: " + safe_terminal_text(config_path)
        ))
        print(dim("기존 설정을 덮어쓰지 않았습니다."))
        return 0

    if not os.path.exists(example_path):
        print(red(
            "예시 설정 파일이 없습니다: " + safe_terminal_text(example_path)
        ))
        return 1

    try:
        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        shutil.copyfile(example_path, config_path)
    except OSError as error:
        print(red("설정 파일 생성 실패: " + safe_terminal_text(error)))
        return 1
    print(green(
        "설정 파일을 생성했습니다: " + safe_terminal_text(config_path)
    ))
    print(dim("이제 roots[].path, authorNames, authorEmails를 본인 환경에 맞게 수정하세요."))
    return 0


def _has_placeholder(values, placeholders):
    return any(str(value).strip() in placeholders for value in values)


def _check_git():
    """Git 실행 가능 여부와 최소 버전 충족 여부를 확인한다."""
    git_path = shutil.which("git")
    if not git_path:
        return None, "Git 실행 파일을 찾을 수 없습니다."

    try:
        result = subprocess.run(
            [git_path, "--version"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except (OSError, UnicodeError, subprocess.TimeoutExpired) as error:
        return None, f"Git 버전 확인 실패: {error}"

    version_output = (result.stdout or result.stderr or "").strip()
    if result.returncode != 0:
        detail = version_output or f"종료 코드 {result.returncode}"
        return None, f"Git 버전 확인 실패: {detail}"

    match = re.search(r"\bgit version (\d+)\.(\d+)(?:\.(\d+))?", version_output)
    if not match:
        detail = version_output or "버전 출력 없음"
        return None, f"Git 버전을 파싱할 수 없습니다: {detail}"

    parsed_version = tuple(int(part or 0) for part in match.groups())
    if parsed_version < MIN_GIT_VERSION:
        current_version = ".".join(str(part) for part in parsed_version)
        return None, (
            f"Git {MIN_GIT_VERSION_TEXT} 이상이 필요합니다. "
            f"현재 버전: {current_version}"
        )

    return version_output, None


def run_doctor():
    """설정과 실행 환경을 점검한다."""
    config_path = os.path.normpath(CONFIG_PATH)
    print(cyan("Daily Code Learn doctor"))

    git_version, git_error = _check_git()
    if git_error:
        print(red(f"- {safe_terminal_text(git_error)}"))
    else:
        print(green(
            f"- Git 확인: {safe_terminal_text(git_version)} "
            f"(최소 {MIN_GIT_VERSION_TEXT})"
        ))

    try:
        _load_env()
    except ConfigError as e:
        print(red(f"- {safe_terminal_text(e)}"))
        return 1

    if not os.path.exists(config_path):
        print(red(f"- 설정 파일 없음: {safe_terminal_text(config_path)}"))
        print(dim("  python3 generate.py --init 으로 설정 파일을 만든 뒤 수정하세요."))
        return 1

    try:
        config = _read_config_file(config_path)
    except ConfigError as e:
        print(red(f"- {safe_terminal_text(e)}"))
        return 1

    validation_errors = validate_config(config)
    has_error = bool(validation_errors) or git_error is not None
    for error in validation_errors:
        print(red(f"- {safe_terminal_text(error)}"))

    roots = config.get("roots", []) if isinstance(config, dict) else []
    seen_repositories = {}
    if isinstance(roots, list):
        for root in roots:
            if not isinstance(root, dict):
                continue

            name = root.get("name")
            raw_label = (
                name.strip()
                if isinstance(name, str) and name.strip()
                else "이름 없음"
            )
            label = safe_terminal_text(raw_label)
            root_path = root.get("path")
            author_names = root.get("authorNames", [])
            author_emails = root.get("authorEmails", [])
            max_depth = root.get("maxDepth", 1)

            if (
                isinstance(root_path, str)
                and os.path.isdir(root_path)
                and isinstance(max_depth, int)
                and not isinstance(max_depth, bool)
                and max_depth >= 1
            ):
                try:
                    repo_paths = scan_repos(root_path, max_depth=max_depth)
                except (OSError, UnicodeError, ValueError) as error:
                    print(red(
                        f"- [{label}] 저장소 탐색 실패: "
                        f"{safe_terminal_text(error)}"
                    ))
                    has_error = True
                else:
                    valid_repo_count = 0
                    for repo_path in repo_paths:
                        try:
                            validate_worktree(repo_path)
                        except GitCommandError as error:
                            print(red(
                                f"- [{label}] 손상되었거나 유효하지 않은 저장소: "
                                f"{safe_terminal_text(repo_path)}: "
                                f"{safe_terminal_text(error)}"
                            ))
                            has_error = True
                            continue

                        try:
                            repository_identity = get_path_identity(repo_path)
                        except OSError as error:
                            print(red(
                                f"- [{label}] 저장소 정체성 확인 실패: "
                                f"{safe_terminal_text(repo_path)}: "
                                f"{safe_terminal_text(error)}"
                            ))
                            has_error = True
                            continue
                        previous = seen_repositories.get(repository_identity)
                        if previous is not None:
                            print(red(
                                f"- [{label}] 동일한 저장소가 여러 root에서 "
                                f"발견되었습니다: [{previous}] "
                                f"{safe_terminal_text(repo_path)}"
                            ))
                            has_error = True
                            continue
                        seen_repositories[repository_identity] = label
                        valid_repo_count += 1

                    root_message = (
                        f"- [{label}] root 확인: {safe_terminal_text(root_path)} "
                        f"({valid_repo_count}개 git 저장소)"
                    )
                    if valid_repo_count == 0:
                        print(yellow(root_message))
                        if repo_paths:
                            print(yellow(
                                "  사용할 수 있는 고유 worktree 저장소가 없습니다."
                            ))
                        else:
                            print(yellow(
                                f"  maxDepth={max_depth} 범위에서 저장소를 "
                                "찾지 못했습니다."
                            ))
                        has_error = True
                    else:
                        print(green(root_message))

            if (
                isinstance(author_names, list)
                and _has_placeholder(author_names, PLACEHOLDER_NAMES)
            ):
                print(yellow(f"- [{label}] authorNames placeholder 값이 남아 있습니다."))
                has_error = True

            if (
                isinstance(author_emails, list)
                and _has_placeholder(author_emails, PLACEHOLDER_EMAILS)
            ):
                print(yellow(f"- [{label}] authorEmails placeholder 값이 남아 있습니다."))
                has_error = True

    telegram = config.get("telegram", {}) if isinstance(config, dict) else {}
    if isinstance(telegram, dict) and telegram.get("enabled") is True:
        missing_env = [
            name for name in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")
            if not os.environ.get(name)
        ]
        if missing_env:
            print(yellow("- 텔레그램 환경변수 없음: " + ", ".join(missing_env)))
            has_error = True
        else:
            print(green("- 텔레그램 환경변수 확인"))

    output_dir = (
        config.get("outputDir", "./reports")
        if isinstance(config, dict)
        else "(invalid)"
    )
    print(dim(f"- outputDir: {safe_terminal_text(output_dir)}"))

    if has_error:
        print(yellow("점검 결과: 수정이 필요한 항목이 있습니다."))
        return 1

    print(green("점검 결과: 기본 설정이 정상입니다."))
    return 0


def load_config():
    try:
        _load_env()
    except ConfigError as e:
        print(red(safe_terminal_text(e)))
        sys.exit(1)

    config_path = os.path.normpath(CONFIG_PATH)
    if not os.path.exists(config_path):
        print(red(
            "설정 파일이 없습니다: " + safe_terminal_text(config_path)
        ))
        print("다음 명령으로 예시 파일을 생성한 뒤 수정하세요:")
        print(dim("  python3 generate.py --init"))
        sys.exit(1)

    try:
        config = _read_config_file(config_path)
    except ConfigError as e:
        print(red(safe_terminal_text(e)))
        sys.exit(1)

    validation_errors = validate_config(config)
    if validation_errors:
        print(red(
            "설정 파일이 올바르지 않습니다: "
            + safe_terminal_text(config_path)
        ))
        for error in validation_errors:
            print(red(f"- {safe_terminal_text(error)}"))
        print(dim("  python3 generate.py --doctor 로 설정을 점검하세요."))
        sys.exit(1)

    telegram = config.get("telegram", {})
    # Runtime credentials come only from the environment. Ignore stale or
    # accidentally persisted values from profiles.json even when env vars are
    # missing, so the warning below cannot be followed by an unintended send.
    telegram.pop("bot_token", None)
    telegram.pop("chat_id", None)
    if telegram.get("enabled", False):
        bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")

        if not bot_token or not chat_id:
            print(yellow(
                "[경고] TELEGRAM_BOT_TOKEN 또는 TELEGRAM_CHAT_ID가 "
                "설정되지 않았습니다. 전송을 요청하면 실패합니다."
            ))
        else:
            telegram["bot_token"] = bot_token
            telegram["chat_id"] = chat_id

        config["telegram"] = telegram

    config.setdefault("outputDir", "./reports")

    return config


def parse_args(argv=None):
    raw_argv = list(argv) if argv is not None else sys.argv[1:]
    parser = argparse.ArgumentParser(description="Daily Code Learn - 오늘 작업한 코드를 마크다운으로 정리")
    parser.add_argument(
        "--version",
        action="version",
        version=f"Daily Code Learn {__version__}",
    )
    utility_group = parser.add_mutually_exclusive_group()
    utility_group.add_argument(
        "--init",
        action="store_true",
        help="config/profiles.json 설정 파일을 예시 파일에서 생성",
    )
    utility_group.add_argument(
        "--doctor",
        action="store_true",
        help="Git, 설정 파일, root 경로, 텔레그램 환경변수를 점검",
    )
    parser.add_argument("--date", type=str, default=None, help="대상 날짜 (YYYY-MM-DD), 미지정 시 오늘")
    parser.add_argument(
        "--include-current-changes",
        action="store_true",
        help="과거 --date에도 현재 staged/unstaged/untracked 변경을 포함",
    )
    parser.add_argument(
        "--check-missed",
        action="store_true",
        help="최근 N일 동안 작업했지만 리포트가 없는 날짜를 점검",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=None,
        help="누락 점검 시 확인할 최근 날짜 수 (기본값: 30)",
    )
    notify_group = parser.add_mutually_exclusive_group()
    notify_group.add_argument(
        "--notify",
        action="store_true",
        help="리포트 생성 직후 텔레그램 알림을 전송",
    )
    notify_group.add_argument(
        "--no-notify",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="디버그 로그 출력",
    )
    args = parser.parse_args(raw_argv)
    date_provided = args.date is not None

    if args.days is not None and not args.check_missed:
        parser.error("--days 는 --check-missed 와 함께만 사용할 수 있습니다.")

    if args.days is None:
        args.days = 30

    if date_provided and args.check_missed:
        parser.error("--date 와 --check-missed 는 함께 사용할 수 없습니다.")

    if (args.init or args.doctor) and (
        date_provided
        or args.check_missed
        or args.notify
        or args.no_notify
        or args.include_current_changes
    ):
        parser.error("--init/--doctor 는 리포트 생성 옵션과 함께 사용할 수 없습니다.")

    if not 1 <= args.days <= MAX_MISSED_DAYS:
        parser.error(
            f"--days 는 1 이상 {MAX_MISSED_DAYS} 이하의 정수여야 합니다."
        )

    today = datetime.now().strftime("%Y-%m-%d")
    if date_provided:
        try:
            parsed_date = datetime.strptime(args.date, "%Y-%m-%d")
            if parsed_date.strftime("%Y-%m-%d") != args.date:
                raise ValueError
        except ValueError:
            parser.error(
                f"잘못된 날짜 형식입니다: {args.date} "
                "(YYYY-MM-DD 형식으로 입력하세요)"
            )
    elif not args.check_missed:
        args.date = today

    if not args.check_missed and args.date == today:
        args.include_current_changes = True

    return args
