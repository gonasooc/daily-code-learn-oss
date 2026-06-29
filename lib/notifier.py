"""텔레그램 알림 모듈 - 리포트 파일을 HTML로 변환하여 텔레그램 메시지로 전송"""

import json
import os
import re
import sys
import urllib.request

# python3 lib/notifier.py 로 직접 실행할 때만 sys.path 보정
if __name__ == "__main__":
    sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), "..")))

from lib.colors import green, yellow, red, cyan, dim

MAX_MESSAGE_LENGTH = 4096


def _escape_html(text):
    """HTML 특수문자 이스케이프"""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _convert_inline_md(escaped_line):
    """이스케이프된 텍스트에서 인라인 마크다운(**bold**, `code`)을 HTML로 변환"""
    # **bold** → <b>bold</b> (이스케이프된 상태이므로 ** 그대로 매칭)
    escaped_line = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escaped_line)
    # `code` → <code>code</code>
    escaped_line = re.sub(r"`(.+?)`", r"<code>\1</code>", escaped_line)
    return escaped_line


def _md_to_telegram_html(md_text):
    """마크다운을 텔레그램 호환 HTML로 변환"""
    lines = md_text.split("\n")
    result = []
    in_code_block = False
    in_table = False

    for line in lines:
        # 코드블록 토글
        if line.startswith("```"):
            if not in_code_block:
                in_code_block = True
                in_table = False
                result.append("<pre>")
            else:
                in_code_block = False
                result.append("</pre>")
            continue

        # 코드블록 내부는 이스케이프만
        if in_code_block:
            result.append(_escape_html(line))
            continue

        # <details>/<summary>/</details> 태그 제거, 내용만 유지
        if line.strip() in ("<details>", "</details>"):
            in_table = False
            continue
        m = re.match(r"<summary>(.*?)</summary>", line.strip())
        if m:
            in_table = False
            result.append(f"<b>{_escape_html(m.group(1))}</b>")
            continue

        # 수평선 → 구분선
        if re.match(r"^-{3,}\s*$", line):
            in_table = False
            result.append("———")
            continue

        # 테이블 처리
        if "|" in line and re.match(r"^\s*\|", line):
            # 구분선 행(|---|---|) → 건너뜀
            if re.match(r"^\s*\|[\s\-:|]+\|\s*$", line):
                continue
            # 셀 파싱
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if not in_table:
                # 헤더행 → 볼드
                in_table = True
                header = " | ".join(cells)
                result.append(f"<b>{_escape_html(header)}</b>")
            else:
                # 데이터행 → 불릿 형태
                row = " | ".join(cells)
                result.append(f"  • {_convert_inline_md(_escape_html(row))}")
            continue
        else:
            in_table = False

        # 제목 → 볼드 (h1~h6)
        m = re.match(r"^(#{1,6})\s+(.*)", line)
        if m:
            result.append(f"<b>{_convert_inline_md(_escape_html(m.group(2)))}</b>")
            continue

        # 블록인용 → 인용 표시
        m = re.match(r"^>\s?(.*)", line)
        if m:
            result.append(f"  ▎ {_convert_inline_md(_escape_html(m.group(1)))}")
            continue

        # 리스트 → 불릿
        m = re.match(r"^(\s*)-\s+(.*)", line)
        if m:
            indent = "  " * (len(m.group(1)) // 2)
            result.append(f"{indent}• {_convert_inline_md(_escape_html(m.group(2)))}")
            continue

        # 순서 리스트 유지
        m = re.match(r"^(\s*)\d+\.\s+(.*)", line)
        if m:
            indent = "  " * (len(m.group(1)) // 2)
            result.append(f"{indent}{_convert_inline_md(_escape_html(line.strip()))}")
            continue

        # 일반 텍스트
        result.append(_convert_inline_md(_escape_html(line)))

    # 코드블록이 닫히지 않은 경우 보정
    if in_code_block:
        result.append("</pre>")

    return "\n".join(result)


def send_telegram_message(bot_token, chat_id, text):
    """Telegram Bot API sendMessage 호출 (HTML 모드)"""
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = json.dumps({
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
    }).encode()

    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.status == 200


def split_message(text, max_length=MAX_MESSAGE_LENGTH):
    """텍스트를 max_length 이하 청크로 분할 (줄 단위, 열린 태그 보정)"""
    lines = text.split("\n")
    chunks = []
    current = ""

    for line in lines:
        candidate = current + line + "\n" if current else line + "\n"
        if len(candidate) <= max_length:
            current = candidate
        else:
            if current:
                chunks.append(current)
            while len(line) + 1 > max_length:
                chunks.append(line[:max_length])
                line = line[max_length:]
            current = line + "\n"

    if current:
        chunks.append(current)

    # <pre> 태그가 청크 경계에서 잘린 경우 보정
    balanced = []
    pre_open = False
    for chunk in chunks:
        if pre_open:
            chunk = "<pre>\n" + chunk
        opens = chunk.count("<pre>")
        closes = chunk.count("</pre>")
        pre_open = (opens - closes) % 2 == 1
        if pre_open:
            chunk = chunk + "\n</pre>"
        balanced.append(chunk)

    return balanced


def send_file_as_messages(bot_token, chat_id, file_path, date):
    """파일 내용을 읽어 HTML 변환 후 분할 메시지로 전송"""
    file_name = os.path.basename(file_path)

    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    html_content = _md_to_telegram_html(content)
    header = f"<b>📋 {_escape_html(date)} - {_escape_html(file_name)}</b>\n\n"

    if len(header) + len(html_content) <= MAX_MESSAGE_LENGTH:
        chunks = [header + html_content]
    else:
        chunks = split_message(html_content)
        chunks[0] = header + chunks[0]
        if len(chunks[0]) > MAX_MESSAGE_LENGTH:
            chunks[0] = chunks[0][len(header):]
            chunks.insert(0, header)

    for i, chunk in enumerate(chunks):
        try:
            send_telegram_message(bot_token, chat_id, chunk)
        except Exception as e:
            print(red(f"  [텔레그램] 전송 실패: {file_name} (파트 {i + 1}) - {e}"))
            return False

    print(green(f"  [텔레그램] 전송 완료: {file_name} ({len(chunks)}개 메시지)"))
    return True


def notify(config, date, output_dir):
    """config 설정에 따라 텔레그램으로 리포트 메시지 전송"""
    telegram = config.get("telegram", {})
    if not telegram.get("enabled", False):
        return True

    bot_token = telegram.get("bot_token")
    chat_id = telegram.get("chat_id")

    if not bot_token or not chat_id:
        print(yellow("[텔레그램] 토큰 또는 chat_id가 설정되지 않았습니다. 전송을 건너뜁니다."))
        return False

    report_dir = os.path.join(output_dir, date)
    if not os.path.isdir(report_dir):
        print(yellow(f"[텔레그램] 리포트 디렉토리가 없습니다: {report_dir}"))
        return False

    md_files = sorted(f for f in os.listdir(report_dir) if f.endswith(".md"))
    if not md_files:
        print(yellow(f"[텔레그램] 전송할 .md 파일이 없습니다: {report_dir}"))
        return False

    print(f"\n{cyan(f'[텔레그램] {len(md_files)}개 파일 전송 시작...')}")
    ok = True
    for name in md_files:
        file_path = os.path.join(report_dir, name)
        if not send_file_as_messages(bot_token, chat_id, file_path, date):
            ok = False
    return ok


def notify_file(file_path, date):
    """단일 파일을 텔레그램으로 전송 (스킬에서 호출용)"""
    from lib.config import load_config

    config = load_config()
    telegram = config.get("telegram", {})
    if not telegram.get("enabled", False):
        print(dim("[텔레그램] 비활성화 상태입니다."))
        return True

    bot_token = telegram.get("bot_token")
    chat_id = telegram.get("chat_id")

    if not bot_token or not chat_id:
        print(yellow("[텔레그램] 토큰 또는 chat_id가 설정되지 않았습니다."))
        return False

    if not os.path.exists(file_path):
        print(red(f"[텔레그램] 파일이 없습니다: {file_path}"))
        return False

    return send_file_as_messages(bot_token, chat_id, file_path, date)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("사용법: python3 lib/notifier.py <파일경로> <날짜>")
        sys.exit(1)

    sys.exit(0 if notify_file(sys.argv[1], sys.argv[2]) else 1)
