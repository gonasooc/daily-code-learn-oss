# Contributing

Thanks for improving Daily Code Learn.

## Local Setup

```bash
git clone https://github.com/gonasooc/daily-code-learn-oss.git
cd daily-code-learn-oss
python3 generate.py --init
python3 generate.py --doctor
```

Edit `config/profiles.json` for your own workspace before generating reports.

## Development

Daily Code Learn intentionally uses only the Python standard library. Do not add runtime dependencies unless the tradeoff is discussed first.

Run tests before opening a pull request:

```bash
python3 -m unittest discover -v
```

Optional syntax check:

```bash
PYTHONPYCACHEPREFIX=/tmp/daily-code-learn-pycache python3 -m py_compile generate.py lib/*.py
```

## Pull Requests

- Keep changes focused on one problem.
- Add or update tests for behavior changes.
- Update `README.md` when user-facing commands or configuration change.
- Avoid committing local files such as `.env`, `config/profiles.json`, or `reports/`.
