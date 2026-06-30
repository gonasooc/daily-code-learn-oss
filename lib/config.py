import argparse
import json
import os
import shutil
import sys
from datetime import datetime

from lib import __version__
from lib.colors import red, yellow, dim, green, cyan
from lib.scanner import scan_repos

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "profiles.json")
EXAMPLE_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "profiles.example.json")
PROJECT_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))


def _load_env():
    """프로젝트 루트의 .env 파일을 읽어 os.environ에 설정"""
    env_path = os.path.join(PROJECT_ROOT, ".env")
    if not os.path.exists(env_path):
        return

    with open(env_path, "r", encoding="utf-8") as f:
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


PLACEHOLDER_EMAILS = {"me@example.com", "your@email.com", "you@example.com"}
PLACEHOLDER_NAMES = {"Your Name", "My Name"}


def init_config():
    """예시 설정 파일을 실제 설정 파일로 복사한다."""
    config_path = os.path.normpath(CONFIG_PATH)
    example_path = os.path.normpath(EXAMPLE_PATH)

    if os.path.exists(config_path):
        print(yellow(f"이미 설정 파일이 있습니다: {config_path}"))
        print(dim("기존 설정을 덮어쓰지 않았습니다."))
        return 0

    if not os.path.exists(example_path):
        print(red(f"예시 설정 파일이 없습니다: {example_path}"))
        return 1

    os.makedirs(os.path.dirname(config_path), exist_ok=True)
    shutil.copyfile(example_path, config_path)
    print(green(f"설정 파일을 생성했습니다: {config_path}"))
    print(dim("이제 roots[].path, authorNames, authorEmails를 본인 환경에 맞게 수정하세요."))
    return 0


def _has_placeholder(values, placeholders):
    return any(str(value).strip() in placeholders for value in values)


def run_doctor():
    """설정과 실행 환경을 점검한다."""
    _load_env()

    config_path = os.path.normpath(CONFIG_PATH)
    print(cyan("Daily Code Learn doctor"))

    if not os.path.exists(config_path):
        print(red(f"- 설정 파일 없음: {config_path}"))
        print(dim("  python3 generate.py --init 으로 설정 파일을 만든 뒤 수정하세요."))
        return 1

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
    except json.JSONDecodeError as e:
        print(red(f"- 설정 JSON 파싱 실패: {e}"))
        return 1

    has_error = False
    roots = config.get("roots", [])
    if not roots:
        print(red("- roots 설정 없음"))
        has_error = True

    for root in roots:
        name = root.get("name", "(이름 없음)")
        root_path = root.get("path", "")
        author_names = root.get("authorNames", [])
        author_emails = root.get("authorEmails", [])

        if not root_path or not os.path.isdir(root_path):
            print(red(f"- [{name}] root 경로 없음: {root_path}"))
            has_error = True
        else:
            repo_count = len(scan_repos(root_path))
            print(green(f"- [{name}] root 확인: {root_path} ({repo_count}개 git 저장소)"))

        if _has_placeholder(author_names, PLACEHOLDER_NAMES):
            print(yellow(f"- [{name}] authorNames placeholder 값이 남아 있습니다."))
            has_error = True

        if _has_placeholder(author_emails, PLACEHOLDER_EMAILS):
            print(yellow(f"- [{name}] authorEmails placeholder 값이 남아 있습니다."))
            has_error = True

    telegram = config.get("telegram", {})
    if telegram.get("enabled", False):
        missing_env = [
            name for name in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")
            if not os.environ.get(name)
        ]
        if missing_env:
            print(yellow("- 텔레그램 환경변수 없음: " + ", ".join(missing_env)))
            has_error = True
        else:
            print(green("- 텔레그램 환경변수 확인"))

    output_dir = config.get("outputDir", "./reports")
    print(dim(f"- outputDir: {output_dir}"))

    if has_error:
        print(yellow("점검 결과: 수정이 필요한 항목이 있습니다."))
        return 1

    print(green("점검 결과: 기본 설정이 정상입니다."))
    return 0


def load_config():
    _load_env()

    config_path = os.path.normpath(CONFIG_PATH)
    if not os.path.exists(config_path):
        print(red(f"설정 파일이 없습니다: {config_path}"))
        print("다음 명령으로 예시 파일을 생성한 뒤 수정하세요:")
        print(dim("  python3 generate.py --init"))
        sys.exit(1)

    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    telegram = config.get("telegram", {})
    if telegram.get("enabled", False):
        bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")

        if not bot_token or not chat_id:
            print(yellow("[경고] TELEGRAM_BOT_TOKEN 또는 TELEGRAM_CHAT_ID가 설정되지 않았습니다. 텔레그램 알림을 비활성화합니다."))
            telegram["enabled"] = False
        else:
            telegram["bot_token"] = bot_token
            telegram["chat_id"] = chat_id

        config["telegram"] = telegram

    config.setdefault("outputDir", "./reports")

    return config


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Daily Code Learn - 오늘 작업한 코드를 마크다운으로 정리")
    parser.add_argument(
        "--version",
        action="version",
        version=f"Daily Code Learn {__version__}",
    )
    parser.add_argument(
        "--init",
        action="store_true",
        help="config/profiles.json 설정 파일을 예시 파일에서 생성",
    )
    parser.add_argument(
        "--doctor",
        action="store_true",
        help="설정 파일, root 경로, 텔레그램 환경변수를 점검",
    )
    parser.add_argument("--date", type=str, default=None, help="대상 날짜 (YYYY-MM-DD), 미지정 시 오늘")
    parser.add_argument(
        "--check-missed",
        action="store_true",
        help="최근 N일 동안 작업했지만 리포트가 없는 날짜를 점검",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=30,
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
    args = parser.parse_args(argv)

    if args.date and args.check_missed:
        parser.error("--date 와 --check-missed 는 함께 사용할 수 없습니다.")

    if (args.init or args.doctor) and (args.date or args.check_missed or args.notify):
        parser.error("--init/--doctor 는 리포트 생성 옵션과 함께 사용할 수 없습니다.")

    if args.days <= 0:
        parser.error("--days 는 1 이상의 정수여야 합니다.")

    if args.date:
        try:
            datetime.strptime(args.date, "%Y-%m-%d")
        except ValueError:
            print(red(f"잘못된 날짜 형식입니다: {args.date} (YYYY-MM-DD 형식으로 입력하세요)"))
            sys.exit(1)
    elif not args.check_missed:
        args.date = datetime.now().strftime("%Y-%m-%d")

    return args
