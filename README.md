# Daily Code Learn

<p align="center">
  <img src="docs/thumbnail.svg" alt="Daily Code Learn" width="100%">
</p>

매일 퇴근 전 터미널 명령 한 번으로 오늘 작업한 코드를 프로젝트별 마크다운으로 정리하는 CLI 도구.
생성된 마크다운은 Claude, Codex 등에 직접 던져서 분석 가능.

## 특징

- Python3 표준 라이브러리만 사용 (의존성 0개)
- macOS/Linux 기본 Python3으로 바로 실행
- 설정한 루트 경로 하위의 git 저장소를 자동 탐색
- 실행 시 `git fetch`로 원격 브랜치 동기화 — pull 없이도 다른 환경에서 push한 커밋 탐지
- 커밋 이력, staged/unstaged 변경 파일을 마크다운으로 출력
- 터미널 출력에 ANSI 색상 적용 (성공/경고/에러 구분)
- 텔레그램 봇을 통한 분석 결과 전송, 필요 시 리포트 전송 (선택)

## 5분 Quickstart

```bash
git clone https://github.com/gonasooc/daily-code-learn-oss.git
cd daily-code-learn-oss

# 설정 파일 생성
python3 generate.py --init

# config/profiles.json에서 roots[].path, authorNames, authorEmails 수정

# 설정 점검
python3 generate.py --doctor

# 오늘 기준 리포트 생성
python3 generate.py
```

생성 결과는 `reports/{날짜}/{프로젝트명}.md`에 저장된다.

## 실행 방법

```bash
# 버전 확인
python3 generate.py --version

# 설정 파일 생성
python3 generate.py --init

# 설정/환경 점검
python3 generate.py --doctor

# 오늘 기준 리포트 생성
python3 generate.py

# 특정 날짜 기준
python3 generate.py --date 2026-03-12

# 생성 직후 리포트까지 보내고 싶을 때만
python3 generate.py --notify

# 최근 30일 기준 누락된 학습일 점검
python3 generate.py --check-missed

# 최근 14일 기준 누락된 학습일 점검
python3 generate.py --check-missed --days 14
```

`--check-missed`는 누락 날짜를 조회만 하지 않고, 선택한 날짜 하루치 리포트를 바로 생성한다.

## 초기 설정

```bash
# 설정 파일 생성
python3 generate.py --init
```

`config/profiles.json`을 본인 환경에 맞게 수정:

```json
{
  "roots": [
    {
      "name": "my-workspace",
      "path": "/path/to/repositories",
      "authorNames": ["My Name"],
      "authorEmails": ["my@email.com"]
    }
  ],
  "outputDir": "./reports",
  "report": {
    "includeUncommittedDiff": true,
    "maxDiffLines": 1200
  },
  "exclude": ["node_modules", ".next", "dist", "build", "coverage",
              "package-lock.json", "yarn.lock", "pnpm-lock.yaml"]
}
```

`reports/`와 `config/profiles.json`은 로컬 생성/설정 파일이므로 public 저장소에서는 추적하지 않는다.

설정이 맞는지 확인:

```bash
python3 generate.py --doctor
```

`--doctor`는 다음 항목을 점검한다:

- `config/profiles.json` 존재 여부와 JSON 파싱 가능 여부
- `roots[].path` 경로 존재 여부
- root 안에서 발견되는 git 저장소 수
- 예시 author 값이 그대로 남아 있는지 여부
- 텔레그램 활성화 시 필요한 환경변수 존재 여부

| 필드 | 설명 |
|------|------|
| `roots[].name` | 워크스페이스 이름 (콘솔 출력용) |
| `roots[].path` | git 저장소들이 모여있는 상위 디렉토리 경로 |
| `roots[].authorNames` | 작성자 이름 |
| `roots[].authorEmails` | git log 필터링에 사용할 이메일 |
| `outputDir` | 리포트 저장 경로 |
| `report.includeUncommittedDiff` | staged/unstaged 변경의 diff 포함 여부 (기본 `true`) |
| `report.maxDiffLines` | 커밋/현재 변경 diff 블록을 최대 몇 줄까지 출력할지 설정 (기본 `1200`) |
| `exclude` | diff 결과에서 제외할 파일/디렉토리 패턴 |
| `telegram.enabled` | 텔레그램 전송 기능 사용 여부 (기본 `false`) |

## 리포트 생성 조건

다음 중 하나라도 해당하면 해당 프로젝트의 리포트가 생성됨:

- 해당 날짜에 커밋이 1개 이상
- staged 변경이 1개 이상
- unstaged 변경이 1개 이상
- untracked 파일이 1개 이상

staged/unstaged 변경은 기본적으로 파일 목록과 diff가 함께 출력된다.
untracked 파일은 파일 목록만 출력된다.
커밋 전 변경 diff가 너무 길거나 민감한 경우 `report.includeUncommittedDiff`를 `false`로 설정하면 파일 목록만 남긴다.

## 누락된 학습일 점검

`--check-missed`는 `작업은 했지만 리포트를 만들지 않은 날짜`를 찾고, 그중 오늘 진행할 날짜 1개를 골라 바로 리포트를 생성한다.

- 판정 단위는 프로젝트가 아니라 날짜 단위
- 기준 데이터는 최근 N일 동안의 author 기준 커밋
- `reports/{날짜}` 안에 프로젝트 리포트 `.md`가 1개 이상 있으면 누락 아님
- `analysis.md`, `codex-analysis.md`, `claude-analysis.md`, `*-analysis.md`만 있는 경우는 누락으로 유지
- 오늘은 아직 회고 전일 수 있으므로 기본 점검 범위에서 제외
- 최신 10개 누락 날짜만 번호로 보여주고, 더 오래된 날짜는 `YYYY-MM-DD`로 직접 입력해 선택
- `Enter`, `q`, `quit` 입력 시 생성 없이 종료
- 날짜를 선택하면 그 날짜만 기존 `--date YYYY-MM-DD` 흐름으로 바로 생성하고, 분석은 별도 단계로 진행

출력 예시:

```text
$ python3 generate.py --check-missed --days 14
[최근 14일] 작업했지만 리포트를 만들지 않은 날짜 2일 (2026-02-28 ~ 2026-03-13)

1. 2026-03-11: 프로젝트 1개, 커밋 1건
  프로젝트: work/admin-web
2. 2026-03-05: 프로젝트 2개, 커밋 4건
  프로젝트: work/api-server, personal/daily-code-learn

번호를 입력하거나 날짜(YYYY-MM-DD)를 직접 입력하세요. 취소하려면 Enter/q/quit
> 2
선택한 날짜: 2026-03-05

  [work] api-server: 커밋 3건, staged 0건, unstaged 0건, untracked 0건 → ./reports/2026-03-05/api-server.md
  [personal] daily-code-learn: 커밋 1건, staged 0건, unstaged 0건, untracked 0건 → ./reports/2026-03-05/daily-code-learn.md

총 2개 프로젝트 리포트 생성 완료 (2026-03-05)

선택한 날짜 리포트 경로: ./reports/2026-03-05
다음 단계: Codex/Claude로 ./reports/2026-03-05 분석 진행
```

## 출력 예시

```
$ python3 generate.py
  [work] admin-web: 커밋 6건, staged 0건, unstaged 0건, untracked 0건 → ./reports/2026-03-12/admin-web.md
  [personal] api-server: 커밋 2건, staged 0건, unstaged 0건, untracked 0건 → ./reports/2026-03-12/api-server.md

총 2개 프로젝트 리포트 생성 완료 (2026-03-12)
```

리포트는 `reports/{날짜}/{프로젝트명}.md` 경로에 저장됨.

## LLM 분석

생성된 리포트에는 커밋별 코드 diff가 포함되어 있어, Claude나 Codex 등에서 직접 참조해 학습용 분석을 생성할 수 있다.

`prompts/analyze.md`에 분석용 프롬프트 템플릿이 포함되어 있으며, 결과는 **전체 커버리지 + 선별 상세** 구조로 생성한다:

- **오늘의 학습 요약**: 핵심 학습 항목 1~3개를 한 줄씩 요약
- **작업 커버리지**: 모든 프로젝트/주요 변경을 표로 정리하고 상세 분석 여부와 이유를 표시
- **상세 학습**: 핵심 항목 1~3개만 변경 의도, 핵심 원리, 실무 메모 중심으로 분석
- **오늘의 한 줄 정리**: 다시 볼 내용 1~3개로 마무리

대안 비교는 학습 가치가 있을 때만 작성한다. 단순 반복 작업, 설정값 변경, 이미지/문구 수정, diff 없는 변경은 `작업 커버리지` 표에 남기고 상세 분석에서 제외한다.

### Claude

```bash
claude
# 세션 진입 후
> reports/2026-03-12 폴더의 리포트를 prompts/analyze.md 기준으로 분석하고 저장 파일은 reports/2026-03-12/claude-analysis.md로 지정해줘
```

### Codex

```bash
codex
# 세션 진입 후
> reports/2026-03-12 폴더의 리포트를 prompts/analyze.md 기준으로 분석하고 저장 파일은 reports/2026-03-12/codex-analysis.md로 지정해줘
```

프롬프트 내용은 `prompts/analyze.md`를 직접 수정해서 본인의 학습 방향에 맞게 조정할 수 있다.

## 텔레그램 알림

텔레그램은 기본적으로 분석 결과 전송용으로 사용한다. `python3 generate.py`는 리포트 파일만 만들고, 전송은 하지 않는다.

### 설정 방법

1. `.env` 파일 생성:
   ```bash
   cp .env.example .env
   ```

2. `.env`에 봇 토큰과 chat ID 입력:
   ```
   TELEGRAM_BOT_TOKEN=
   TELEGRAM_CHAT_ID=
   ```

3. `config/profiles.json`에 텔레그램 활성화:
   ```json
   {
     "telegram": {
       "enabled": true
     }
   }
   ```

`telegram.enabled`는 텔레그램 전송 기능을 사용할지 여부만 결정한다. 이 값이 `true`여도 `python3 generate.py`는 자동 전송하지 않는다.

분석 결과 전송:

```bash
python3 lib/notifier.py reports/2026-04-09/codex-analysis.md 2026-04-09
```

리포트 생성 직후 전송이 꼭 필요할 때만:

```bash
python3 generate.py --notify
```

### 전송 방식

- 마크다운을 텔레그램 호환 HTML로 변환하여 메시지로 전송 (`parse_mode: HTML`)
- 4096자 초과 시 줄 단위로 분할하여 여러 메시지로 전송
- 로컬 `.md` 파일은 기존 마크다운 형식 그대로 유지

| 마크다운 | 텔레그램 표시 |
|---------|-------------|
| `#`~`######` 제목 | **제목** (볼드) |
| `**bold**` | **볼드** |
| `` `code` `` | `인라인 코드` |
| `- 항목` (중첩 포함) | • 항목 (들여쓰기 반영) |
| `` ```code``` `` | `<pre>` 코드블록 |
| `> 인용` | ▎ 인용 표시 |
| `\| 테이블 \|` | 헤더 볼드 + 데이터 불릿 |
| `---` | ——— 구분선 |
| `<details>` | 펼쳐서 표시 |

## Troubleshooting

### 설정 파일이 없다고 나올 때

```bash
python3 generate.py --init
```

이후 `config/profiles.json`을 열어 `roots[].path`, `authorNames`, `authorEmails`를 실제 값으로 수정한다.

### 리포트가 생성되지 않을 때

```bash
python3 generate.py --doctor
```

- root 경로가 실제 git 저장소들의 상위 디렉토리인지 확인한다.
- `authorEmails`가 `git log`에 찍힌 이메일과 같은지 확인한다.
- 해당 날짜에 커밋, staged, unstaged, untracked 변경 중 하나라도 있는지 확인한다.

### diff가 너무 길거나 민감할 때

`config/profiles.json`에서 diff 포함 여부와 최대 줄 수를 조정한다.

```json
{
  "report": {
    "includeUncommittedDiff": false,
    "maxDiffLines": 600
  }
}
```

### 텔레그램 전송이 되지 않을 때

- `.env`에 `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`가 있는지 확인한다.
- `config/profiles.json`에서 `telegram.enabled`가 `true`인지 확인한다.
- 먼저 `python3 generate.py --doctor`로 누락된 환경변수를 확인한다.

## 파일 구조

```
daily-code-learn/
  generate.py                 # CLI 진입점
  lib/
    config.py                 # 설정 로드 + CLI 인자 파싱
    scanner.py                # root 하위 git 저장소 탐색
    git_commands.py           # git 명령어 래퍼 (fetch, log, diff)
    colors.py                 # 터미널 출력 색상 유틸리티 (ANSI)
    collector.py              # 리포트 데이터 수집
    missed_days.py            # 누락된 학습일 점검
    renderer.py               # 마크다운 생성 + 파일 저장
    notifier.py               # 텔레그램 알림 전송
  prompts/
    analyze.md                # LLM 분석용 프롬프트 템플릿
  config/
    profiles.example.json     # 설정 예시
    profiles.json             # 실제 설정 (gitignored)
  .env.example                # 환경변수 템플릿
  .env                        # 실제 환경변수 (gitignored)
  reports/                    # 생성 결과 (gitignored)
```

## Release

현재 버전은 `0.1.0`이다.

```bash
python3 generate.py --version
```

릴리스 기준:

- `python3 -m unittest discover -v` 통과
- `CHANGELOG.md`에 버전별 변경 사항 기록
- Git tag는 `vX.Y.Z` 형식 사용
- GitHub Releases에는 설치/실행 방법, 주요 변경 사항, 알려진 제한을 함께 기록

## License

MIT
