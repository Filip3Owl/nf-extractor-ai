# Contributing

## Setup

```bash
uv sync
uv run pre-commit install --hook-type pre-commit --hook-type commit-msg
```

The hooks run Ruff and mypy on each commit and check the format of the commit message.

## Branching

This project uses [GitHub Flow](https://docs.github.com/en/get-started/using-github/github-flow). `main` is always releasable and only changes through pull requests.

1. Create a short-lived branch from an up-to-date `main`.
2. Commit small, focused changes.
3. Open a pull request and wait for CI to pass.
4. Squash and merge, then delete the branch.

Name branches `<type>/<short-description>`, using the commit types below:

```text
feat/cte-document-type
fix/access-key-padding
docs/evaluation-guide
```

## Commits

Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/):

```text
<type>(<optional scope>): <imperative summary>

<optional body explaining why>
```

| Type | Use for | Version impact |
|---|---|---|
| `feat` | A new capability | Minor |
| `fix` | A bug fix | Patch |
| `perf` | A performance improvement | Patch |
| `docs` | Documentation only | None |
| `test` | Tests only | None |
| `refactor` | Code changes that keep the behavior | None |
| `style` | Formatting only | None |
| `build` | Dependencies and packaging | None |
| `ci` | The CI configuration | None |
| `chore` | Other maintenance | None |
| `revert` | Reverting a previous commit | Depends |

Mark a breaking change with `!`, as in `feat(nfe)!: rename schema fields`. It increases the major version.

Common scopes are `core`, `nfe`, `validators`, `extractors` and `cli`.

## Versioning and releases

The project follows [Semantic Versioning](https://semver.org/). To publish a release:

1. In a `chore/release-x.y.z` branch, update the version in `pyproject.toml` and `src/nf_extractor/__init__.py`, and move the `Unreleased` entries in `CHANGELOG.md` to the new version.
2. Merge the pull request.
3. Tag the merge commit on `main` and push the tag:

   ```bash
   git tag -a vx.y.z -m "vx.y.z"
   git push origin vx.y.z
   ```

## Quality requirements

CI requires all of the following, on every supported Python version:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
```

Tests must not call real APIs or include real fiscal documents. Use the simulated HTTP transport in `tests/test_claude_extractor.py` and synthetic identifiers.

Public modules, classes and functions need Google-style docstrings, and significant design decisions get a record in [`docs/adr/`](docs/adr/).
