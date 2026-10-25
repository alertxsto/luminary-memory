# Contributing

Thanks for helping build luminary-memory.

## Setup

```bash
git clone <repo> && cd luminary-memory
pip install -e ".[dev]"
```

## Development workflow

1. Create a branch from `develop`: `git checkout develop && git checkout -b feat/your-change`.
2. Write a failing test first (`tests/`).
3. Implement the minimal change.
4. Update the tracked guide that owns the changed contract and the matching
   static website guide in `website/js/docs-guides.js`. Keep ignored planning
   notes under `docs/` out of the public source.
5. Run the checks:

```bash
python -m pytest
python -m ruff check src tests hermes/hooks
node --check website/js/docs-guides.js
```

5. Commit with a conventional message.

### Native plugin packages

Use the latest Node.js 22 patch (at least 22.22.2) and Python 3.11+ from the
repository root:

```bash
python -m pip install -e ".[dev]"
npm ci --ignore-scripts
npm run build:plugins
npm run test:plugins
npm run pack:plugins
```

The private root npm workspace is build tooling, not a publishable package.
The three Luminary-maintained packages are `luminary-memory-pi`,
`luminary-memory-opencode`, and `luminary-memory-omp`. "Maintained" does not
imply endorsement by pi, OpenCode or omp, ownership of an npm name, or that an
npm release already exists.

Edit the canonical adapters under
`src/luminary_memory/integrations/assets/`, not generated bundles. The build
produces each `plugins/<agent>/dist/index.js` and copies the root license into
the package. **A source checkout of `plugins/<agent>` without a build has no
`dist` entry point and is not an installable plugin.** Packaging writes local
installable tarballs to `artifacts/plugins/*.tgz`; it does not publish them.
Use the instructions in each package README to install a built local directory
or tarball into its host.

The Node tests must be able to start the real Python bridge. Keep the editable
Python installation available on `PATH`, or set `LUMINARY_PYTHON` to its Python
executable. Package installation never installs Python dependencies, downloads
models or runs an automatic pip/postinstall script. The existing Python-wheel
copy installer is a separate installation path; remove copied hooks before
enabling a native package so memory events are not registered twice.

CI runs these same npm commands on the latest Node 22 patch with Python 3.11
and an editable Python installation, then uploads the tarballs as the
`native-plugin-packages` artifact. The real-model release gate below remains
separate from the package tests.


## Branch model

- **`develop`**, integration branch. **All pull requests target `develop`.**
- **`main`**, stable release branch, protected. Only maintainers merge release
  commits into it (feature → develop → main → tag).

## Release gate

Tagging `v*` publishes to PyPI through `.github/workflows/publish.yml`, and
`pypi` has a hard prerequisite: the `real-model` job. It runs

```bash
python scripts/smoke-real-model.py --report real-model-gate.json
```

which drives public `MemoryClient.recall` end to end on an isolated SQLite store
with the real default embedding model and asserts **which facts come back**:

- the current scoped deploy fact for both an exact and a paraphrased question;
- an off-topic but graph-linked documentation row is not returned;
- an expired row, another tenant's row and a scoped query stay inside their
  boundaries;
- unanswerable queries abstain.

It fails closed — a wrong model, a failed download or a failed inference aborts
the job — and the JSON report is uploaded as an artifact even when it fails.
Run it locally before tagging; it is not part of the unit suite because it needs
the real ONNX model.

A gate that passes on a confident wrong answer is worse than no gate. When the
gate fails, fix the retrieval defect; never relax the gate or swap in a stub
embedder.

### Versioning and release assets

Before a release, use the existing version synchronizer from the repository
root, for example:

```bash
bash scripts/bump-version.sh 0.3.2
```

It synchronizes the Python version, all three plugin manifest versions and the
workspace versions in `package-lock.json`, preserving other JSON metadata.
The private root `package.json` has no version. Review the generated changelog
entry, then run the Python checks, native package commands and real-model gate
before committing the release changes and creating the matching `vX.Y.Z` tag.

The publish workflow builds, tests and packs native plugins, checks that every
manifest matches `pyproject.toml`, and verifies the exact three nonempty
tarballs contain a built entry point, README and license. Tag releases must
also match `v<version>`. Both this package job and the existing real-model gate
must pass before PyPI publication. After PyPI succeeds, tag pushes attach the
Hermes skill zip and those exact `.tgz` files to the GitHub release, even when
npm publication is disabled. Missing or mismatched packages fail closed.

Manual `workflow_dispatch` keeps the Python publication path: it performs the
same gates and builds, but does not create GitHub release assets or publish to
npm, even if dispatched from a tag. A tag push, not a manual dispatch, is
required for those external release actions.

### Release notes style

Write structured, human-readable notes for the actual release: a descriptive
version title, a short summary, and readable `##` feature sections with normal
prose and focused bullets. These formatting rules are version-independent.

Never leave a published release empty or asset-only. Do not use small/subscript
HTML, wrap the whole description in a code block, or substitute a raw commit
dump for release notes. Reserve code blocks for short installation commands.
State only shipped behavior and verified registry availability.

The workflow attaching assets does not finish the release. Fill in the release
notes and inspect the actual GitHub rendering before reporting completion.

### Optional npm trusted publishing

npm publication is **disabled unless** the repository Actions variable
`PUBLISH_NPM_PLUGINS` is exactly `true`. Leave it unset while establishing
package ownership and registry configuration. Local builds and downloadable
release tarballs do not require npm publishing access.

Before enabling it:

1. Establish maintainer-controlled ownership of all three exact npm names:
   `luminary-memory-pi`, `luminary-memory-opencode`, and `luminary-memory-omp`.
   Availability is not ownership. Complete any initial package creation or
   authenticated bootstrap required by npm separately; this workflow does not
   reserve names or pretend to bootstrap trusted publishing.
2. Configure an npm **trusted publisher for each package** for the correct
   GitHub owner/repository, workflow filename `publish.yml`, and environment
   name `npm`. Allow direct `npm publish` (a stage-only publisher cannot run
   this workflow). Each manifest's `repository.url` must match that GitHub
   repository. See [npm's trusted publishing requirements](https://docs.npmjs.com/trusted-publishers/).
3. Configure the GitHub `npm` deployment environment and its protection rules;
   keep the existing `pypi` environment and PyPI trusted publisher configured
   independently. Protect release tags and restrict who can change the opt-in
   variable or approve deployments.
4. Only after all three package publishers are ready, set the repository
   variable `PUBLISH_NPM_PLUGINS=true` and push a new, version-matched tag.

The npm job runs on a GitHub-hosted runner with the latest Node 22 patch and
npm `^11.5.1` (trusted publishing requires npm 11.5.1+ and Node 22.14+).
It requests `id-token: write`, downloads the already validated tarballs from
the same workflow run, and publishes each exact tarball only after the
real-model gate and PyPI job succeed. It never rebuilds a package at publish
time. Publishing uses `--access public --ignore-scripts` against
`https://registry.npmjs.org`; no npm token secret, credential logging or
token-based fallback is configured.

The workflow's default permission is `contents: read`. The PyPI job requests
`id-token: write` for its existing trusted publishing and `contents: write` to
attach GitHub release assets; the optional npm job requests only
`contents: read` and `id-token: write`. Neither local development commands nor
manual Python releases force npm publication.

The three npm uploads are sequential, not transactional. If registry
authorization or an upload fails, the job fails; it does not mask the error,
republish an existing immutable version or fall back to credentials. Inspect
which versions actually reached npm before planning recovery. Fix npm
configuration without rerunning a successful PyPI upload blindly; npm
publication must continue to use the validated release tarballs.


## Commit conventions

- `feat:`, new feature
- `fix:`, bug fix
- `docs:`, documentation only
- `improve:`, refactor or enhancement without behavior change
- `chore:`, build/tooling

## Coding standards

- Python 3.11+, type-hinted.
- `ruff` clean, `pytest` green.
- TDD where feasible, test first, then implement.
- Keep the public API (`MemoryClient`) stable; add rather than break.
- Full-source coverage is reported and must not regress from the current
  evidence-backed baseline (`83%`, 5,037 statements). Every changed behavior
  needs a targeted regression or invariant test; do not inflate coverage with
  tests that only execute lines without checking outcomes. PostgreSQL-only
  branches are verified separately by the pgvector integration job.

### Long-run checks

Changes to ingest, recall, lifecycle or retention must also survive a soak run,
because those defects only appear across cycles:

```bash
python scripts/soak-test.py --cycles 400 --per-cycle 5 --report /tmp/soak.json
```

It fails on a lost control fact, a no-answer query that starts returning rows,
or recall p50 growing more than `3x` between the first and last fifth of the
run. See [Lifecycle](docs/lifecycle.md#long-run-behaviour) for what it measures
and the current observed numbers.

## AI assistance notice

If you use **any kind of AI assistance** to contribute to luminary-memory, please
disclose it in the pull request together with the extent of the usage. For
example:

> This PR was written primarily by Claude Code.
>
> I consulted ChatGPT to understand the codebase, but the solution was fully
> authored manually.

This helps reviewers apply the right level of scrutiny. AI assistance isn't
always perfect, even when used with the utmost care, a quick disclosure goes a
long way. Please don't use AI to write the pull request description or
contributor communication; keep it concise and in your own voice.

## Pull requests

- One logical change per PR.
- Target the **`develop`** branch.
- Link the issue if applicable.
- CI must pass before merge.
- Automated checks run on every PR:
  - **CI**, unit tests (Python 3.11 & 3.12) + lint.
  - **pgvector integration**, real Postgres round-trips (HNSW, JSONB, rollback).
  - **Native plugin packages**, Node 22 build/tests/local pack with the actual
    Python bridge available; uploads all three installable `.tgz` artifacts.
  - **Triage**, auto-labels the PR and welcomes first-time contributors.
  - **Contributor check**, a soft account/language triage hint for maintainers.

## Testing

Run the full suite (SQLite + unit tests) locally:

```bash
python -m pytest          # 505 passed, 3 skipped at the current baseline
python -m ruff check src tests hermes/hooks
```

Coverage (full-source baseline):

```bash
python -m pytest --cov=luminary_memory --cov-report=term
```

The current local baseline is `83%` (`5,037` statements, `881` missed). The
number is intentionally reported honestly while the defensive PostgreSQL and
failure branches continue to receive integration coverage; the quality gate
is the invariant-focused test suite plus the CI/verification coverage gate
`--fail-under=82`.

### Postgres / pgvector integration tests

`tests/test_backend_pgvector.py` contains real-Postgres round-trips that are
**skipped unless `LUMINARY_PG_DSN` is set**. CI provides a Postgres service for
these (see `.github/workflows/ci.yml`). To run them locally:

```bash
# spin up a throwaway Postgres with the pgvector extension
docker run -d --name luminary-pg -p 5432:5432 \
  -e POSTGRES_USER=luminary -e POSTGRES_PASSWORD=luminary -e POSTGRES_DB=luminary \
  pgvector/pgvector:pg16

# point the tests at it
export LUMINARY_PG_DSN=postgresql://luminary:***@localhost:5432/luminary
python -m pytest tests/test_backend_pgvector.py -v
```
