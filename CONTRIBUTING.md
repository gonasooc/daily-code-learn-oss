# Contributing

Thanks for improving Daily Code Learn.

## Local Setup

Development requires Git 2.37.0 or newer and Python 3.10 or newer. The CLI has
no third-party runtime dependencies.

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

Run the syntax check as well:

```bash
PYTHONPYCACHEPREFIX=/tmp/daily-code-learn-pycache python3 -m py_compile generate.py lib/*.py tests/*.py
```

CI runs the unit test suite on Linux with Python 3.10 through 3.14 and includes
a macOS smoke-test job.

## Pull Requests

- Keep changes focused on one problem.
- Add or update tests for behavior changes.
- Keep `README.md` and `docs/README.ko.md` aligned when user-facing commands,
  configuration, output paths, or behavior change.
- Avoid committing local files such as `.env`, `config/profiles.json`, or `reports/`.
