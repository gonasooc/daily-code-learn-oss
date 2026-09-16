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

## Release

A change that alters behavior adds its own bullet under `## Unreleased` in
`CHANGELOG.md`, in the commit that makes the change. The release only moves
those bullets under a version heading; it does not write them.

Releasing is manual. Run it from `main` with a clean working tree.

```bash
# 1. Bump the version in three places, then verify:
#      CHANGELOG.md               insert "## vX.Y.Z - YYYY-MM-DD" above the Unreleased bullets
#      lib/__init__.py            __version__
#      tests/test_cli_config.py   the version assertion
python3 -m unittest discover

# 2. Commit, tag, push.
git add CHANGELOG.md lib/__init__.py tests/test_cli_config.py
git commit -m "chore: release vX.Y.Z"
git tag -a vX.Y.Z -m "Daily Code Learn vX.Y.Z"
git push origin main
git push origin vX.Y.Z

# 3. Publish the release page.
gh release create vX.Y.Z \
  --title "vX.Y.Z - <one-line summary>" \
  --notes-file <notes.md> \
  --latest
```

Step 3 is not optional and nothing else performs it. Pushing a tag only lists it
under `/tags`; the entry on `/releases` is a separate object, and CI does not
create one.

Write the notes by hand. They open with a sentence on what the release is for,
then `## Changed`, `## Notes` for anything that does not change but is worth
saying, and an `## Upgrade` block with `git pull` and the expected
`python3 generate.py --version` output. Follow the previous release.
