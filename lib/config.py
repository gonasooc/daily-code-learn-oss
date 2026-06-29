import argparse
import json
import os
import sys
from datetime import datetime

from lib.colors import red, yellow, dim

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


def load_config():
    _load_env()

    config_path = os.path.normpath(CONFIG_PATH)
    if not os.path.exists(config_path):
        print(red(f"설정 파일이 없습니다: {config_path}"))
        print("다음 명령으로 예시 파일을 복사한 뒤 수정하세요:")
        print(dim("  cp config/profiles.example.json config/profiles.json"))
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


def parse_args():
    parser = argparse.ArgumentParser(description="Daily Code Learn - 오늘 작업한 코드를 마크다운으로 정리")
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
    args = parser.parse_args()

    if args.date and args.check_missed:
        parser.error("--date 와 --check-missed 는 함께 사용할 수 없습니다.")

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
