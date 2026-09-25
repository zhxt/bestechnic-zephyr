# Contributing

[简体中文](CONTRIBUTING.zh-CN.md)

## Prepare a workspace

Follow [setup and build](docs/getting-started.md), using the Zephyr, CMSIS, CMSIS_6, and HAL commits pinned by [west.yml](west.yml) and the matching toolchain. Create short-lived `feat/*` or `fix/*` branches from the evolving `main` branch.

For a first contribution:

1. Create a short-lived branch from `main`.
2. Read the [architecture guide](docs/architecture.md), implement the change, and update affected documentation.
3. Choose appropriate [pre-commit checks](#pre-commit-validation) and record results and missing validation.
4. Stage only related changes and review them with `git -C bestechnic-zephyr diff --cached`.
5. Follow the [commit format](#commit-format) and describe behavior and validation in the PR.

English is the default documentation language; update corresponding English and Chinese pages together when changing documented behavior. Keep the README concise. [Testing](docs/testing.md) covers builds, host regressions, and hardware validation.

When changing drivers, defaults, or supported features, update the [hardware support table](docs/hardware/bes2700yp.md#supported-features) and [README status summary](README.md#current-support). Distinguish implemented behavior, default enablement, and validation. Hardware claims in release records must reference the tested image SHA256 and report.

## Scope and files

The [architecture guide](docs/architecture.md#directory-responsibilities) describes each directory. Keep BTH and M55 application-private directories separate. Verify origin and licensing before adding or moving files. Use applicable SPDX identifiers for project-owned source and configuration files that support comments; explain documentation and metadata licensing in [origin and licensing](THIRD_PARTY_NOTICES.md). Preserve third-party notices without assuming the project license covers them.

For new files, check the build and archive rules in [scripts/project_files.json](scripts/project_files.json). Existing directory rules collect matching source files; add new directories, file types, or documents to the manifest when needed. Build inputs must also be in the source archive. Register binary test fixtures and their origin.

The `build` file list and build dependencies determine firmware identity. Ordinary documentation, tests, and editor settings are not build inputs, but changing the list itself can change that identity. See [build identity and provenance](docs/architecture.md#build-identity-and-provenance).

Follow [.editorconfig](.editorconfig) and neighboring code: UTF-8, LF, four-space Python indentation, and local C/assembly style. Separate unrelated formatting. Write outputs under the workspace `build/` or a dedicated temporary directory; keep hardware evidence outside the source repository.

## Pre-commit validation

Choose checks according to impact:

| Change | Required validation |
|---|---|
| Documentation | Formatting and repository checks; review changed links, anchors, and example arguments |
| Scripts or tests | Repository checks and relevant host tests; add a build check if build behavior changes |
| Build, dependencies, or memory layout | Repository checks, host tests, clean build, offline audit, and hardware validation when behavior changes |
| Startup, drivers, or IPC | Repository checks, relevant host tests, clean build, offline audit, and corresponding hardware validation |

From the [initialized workspace root](docs/getting-started.md#initialize-and-check-dependencies):

```sh
git -C bestechnic-zephyr diff --check
.venv/bin/python bestechnic-zephyr/scripts/check_repo.py
```

For staged changes, also run `git -C bestechnic-zephyr diff --cached --check`. The repository checker verifies local link targets, but not heading anchors or shell examples. It should report `status: pass` and `issues: []`.

For host regressions:

```sh
.venv/bin/python bestechnic-zephyr/scripts/test_host.py
```

Follow [testing](docs/testing.md) for clean builds, offline audit, and hardware validation. List actual results in commits and PRs; identify anything not run. The validation profiles belong to the current test applications. Business applications need not copy their scenarios, durations, or stop behavior.

## Commit format

Use the [Zephyr commit guidelines](https://docs.zephyrproject.org/latest/contribute/guidelines.html#commit-message-guidelines) and [contributor expectations](https://docs.zephyrproject.org/latest/contribute/contributor_expectations.html) as references, with these repository conventions:

- Use `area: summary`, optionally `area: component: summary`, such as `doc: clarify build prerequisites` or `boards: bes2700yp_devkit: describe BTH target`. Choose the area from the changed files and existing history.
- Keep the entire English subject under 72 characters, followed by a blank line. Include a body explaining the problem, reason, assumptions, and actual validation; normally wrap at 75 characters.
- Keep each commit focused. Remove temporary fixups before review and avoid unrelated formatting or merge commits.
- Each contribution needs a [DCO](https://docs.zephyrproject.org/latest/contribute/guidelines.html#developer-certification-of-origin-dco) `Signed-off-by` from the actual contributor, using the real name and email matching the author for self-authored commits. Retain existing sign-offs when editing another person's commit and add the actual contributor's own sign-off.
- The contributor must make the DCO certification. `git commit -s` adds the trailer after that decision; automation cannot certify on someone's behalf. A sign-off is not a GPG signature or authorization to redistribute third-party material.
- Link issues with an explicit repository path; external evidence may use `Link:`. Describe behavior and validation in the PR, marking unperformed hardware testing as pending.

Example format; replace the identity and validation with real values:

```text
doc: describe contribution requirements

Document the commit format and the repository validation workflow.
This gives contributors a consistent checklist before review.

Validation: checked document links and ran the repository checks.

Signed-off-by: Your Full Name <your.email@example.com>
```

## Branches and releases

Maintainers manage release candidates and tags. `main` accepts changes that meet applicable checks. Use a temporary `release/*` branch for repeated hardware validation rather than a permanent `develop` branch. Before freezing a candidate, consolidate fixups while preserving independently reviewable changes.

Identify a firmware candidate by a fixed commit, `vX.Y.Z-rcN` tag, and image SHA256. Do not rebase, squash, or edit a frozen candidate; later changes create a new candidate. A first public source snapshot may retain `hardware: not_tested` and HAL `unconfirmed` status when both are disclosed accurately; it must not be described as hardware-validated firmware or as granting vendor authorization. A validated firmware release additionally requires repository checks, host regressions, clean build, offline audit, and hardware validation tied to its image SHA256. Fast-forward the validated commit to `main` before adding a final tag. If `main` has advanced, create and validate another candidate. Never move a release tag.

### Candidate package provenance

Ordinary builds use `development` mode, which permits local integration and HAL edits and archives the actual files. For a formal candidate, build from separate clean checkouts with `-DBES_FORMAL_PACKAGE=ON` in the west build command or `--formal` at the [CI entry point](docs/testing.md#ci-entry-point). Integration and HAL must stay at fixed, clean Git commits throughout the build; Zephyr, CMSIS, and CMSIS_6 must satisfy the module lock.

Downloaded HAL libraries are not tracked by Git, so a clean checkout does not prove their bytes. Formal packaging checks committed files and blob hashes separately, adds the complete HAL inputs to `hal-consumer.tar`, and rejects changes during packaging.

`release/manifest.json` records archive mode; `release/source-provenance.json` records revisions, worktree state, hashes, and blob provenance. See [build outputs](docs/getting-started.md#build-outputs-and-verification). A change to the integration commit, pinned modules, or `hal-release.sha256` requires a new build and provenance record. Formal mode verifies provenance; hardware results and distribution status are recorded separately.
