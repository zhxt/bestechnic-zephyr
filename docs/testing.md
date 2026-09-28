# Testing and Release Validation

[简体中文](testing.zh-CN.md)

Prepare the workspace, pinned HAL module, and toolchain with [setup and build](getting-started.md). Run commands from the workspace root containing `bestechnic-zephyr/`, `.venv/`, and `zephyr/`; build commands use the `ZEPHYR_BASE` and `CROSS_COMPILE` variables set there.

| Stage | What it checks | Evidence |
|---|---|---|
| Repository | File scope, west/lock agreement, local document targets, HAL hashes | `check_repo.py` output |
| Host regression | Protocol, driver models, log parsing, and packaging | `test_host.py` output and exit code |
| Build and offline audit | Firmware, load layout, core matching, package checksums | Build logs, `release/offline-validation.json`, `release/SHA256SUMS` |
| Resource ownership | Generated DTS/config access boundaries and conflicts | `check_resources.py` report outside the package |
| Hardware validation | Boot, dual-core operation, and messages on the target board | Raw serial logs, packaged analyzer reports, operation record |
| Publication preparation | Frozen provenance, evidence, and accurate distribution-status disclosure | [Maintainer release guidance](../CONTRIBUTING.md#branches-and-releases) |

## Repository and host checks

```sh
.venv/bin/python bestechnic-zephyr/scripts/check_repo.py
.venv/bin/python bestechnic-zephyr/scripts/test_host.py
```

The repository check should return `status: pass` and empty `issues`. `publication_pending` separately reports unconfirmed HAL redistribution evidence, an unset HAL `public_source_url` field, and any clean-revision or remote-configuration gaps. `--for-publication` requires clean commits and configured remotes but does not turn `unconfirmed` into an authorization claim.

Host regressions cover actual message code, protocol validation, snapshot preemption, mailbox/UART models, log parsing, negative image-packaging cases, and archive boundaries. Expect `OK` and exit code 0. Host models do not replace board tests.

## Build validation

Use the default `main` build in [build instructions](getting-started.md#build) at `build/bes2700yp/main`. Afterward, check the [package checksums](getting-started.md#build-outputs-and-verification) and [offline audit](architecture.md#offline-audit). Neither establishes hardware operation.

### Static resource ownership

[check_resources.py](../scripts/check_resources.py) reads both cores' generated
`bth.dts`, `m55.dts`, `bth.config` and `m55.config` from a complete release package:

```sh
.venv/bin/python bestechnic-zephyr/scripts/check_resources.py \
  --release build/bes2700yp/main/release --zephyr-base zephyr \
  --output build/bes2700yp/main-resources.json
```

Use the workspace's pinned Zephyr revision for its DTS parser. The checker combines
the existing runtime resource and bootstrap contracts with the
[audit policy](../scripts/resource_ownership.json). It checks the current dual-core
applications' CPU clock/configuration, enabled MMIO claims, local IRQ ranges and
conflicts, mailbox field sharing, BTH code/data aliases, and shared-memory
reservations. Identical private-core addresses and IRQ numbers on different cores
are allowed. Bootstrap UART and its pads remain reserved when its DTS node is
disabled. General GPIO/pinctrl encodings, address translations, and new
clock/reset/power dependencies require policy review and are rejected, rather than
treated as granted resources.

Expect `status: pass`, `errors: []` and exit code 0. A conflict or unreadable input
returns exit code 1; command-line errors return 2. `unconfirmed` separately lists
missing board wiring, voltage, IRQ-route and timebase evidence; passing static
checks does not resolve these items. This check supplements the ELF/physical-bank
audit and does not enforce runtime access or establish hardware operation.

Reports record checker, policy, contract, parser and DTS/config hashes. Save them
outside the source and frozen package. Compatible existing packages may be checked
without rebuilding; preserve their original checksums and hardware evidence. Audit
scripts and policy are archived source, not firmware configuration. Compare actual
build inputs before deciding whether a tooling-only change needs another firmware
build or board test. A new formal candidate still needs its own build/provenance.

CI runs this check after package checksum verification and rejects conflicts before
accepting the artifact. A direct `west build` runs the existing image/ELF audit;
run the command above separately for resource ownership.

### CI entry point

[scripts/ci.py](../scripts/ci.py) can run locally or in CI. For repository and host checks only:

```sh
.venv/bin/python bestechnic-zephyr/scripts/ci.py \
  --workspace . --output build/ci-host
```

To also build the four message profiles:

```sh
.venv/bin/python bestechnic-zephyr/scripts/ci.py \
  --workspace . --output build/ci-matrix \
  --profiles ipc-sequential ipc-backpressure ipc-fault-injection ipc-backpressure-1h \
  --cross-compile "${CROSS_COMPILE:?Set up the toolchain first}"
```

`--output` must be a new directory outside the source repository; choose another directory on reruns. Without `--profiles`, the script checks repository and host tests but does not build firmware. The output contains `summary.json`, `repository.log`, `host.log`, selected build logs/directories, and `<profile>-resources.json` resource reports. Expect summary `status: pass`, zero exit codes, and checked package `SHA256SUMS`. The script does not touch hardware; `hardware` remains `not_tested`. Formal candidates may add `--formal`; see [candidate provenance](../CONTRIBUTING.md#candidate-package-provenance).

## Validation profiles

`BES_VALIDATION_PROFILE` selects validation behavior, not a source revision. [validation_profiles.py](../scripts/validation_profiles.py) defines the profiles; [firmware.py](../scripts/firmware.py) generates both core configurations. The four message profiles share the original IPC ABI. `m55-restart` uses a separate retained-memory lifecycle contract.

The default `ipc-backpressure` runs bidirectional backpressure traffic for 600 seconds. BTH observes until 610 seconds, ends validation, and stops M55. This bounded behavior is specific to the validation app; production applications should set their own lifetime.

`layout.json` records `validation_schema=1` and `validation_profile`; identity and release manifest use build schema 3. Analyzers check parameters, identities, and runtime records, rejecting unknown versions or mismatches. Keep the packaged `validation_profiles.py` and verify `SHA256SUMS` when copying a package.

| Profile | Message behavior and completion | Heartbeat observation ends |
|---|---|---:|
| `ipc-sequential` | 10,000 messages in each direction, then heartbeat observation | At least 600 s (long) |
| `ipc-backpressure` | Continuous bidirectional traffic for 600 s, including slow consumers and counter closure | 610 s |
| `ipc-fault-injection` | Fault injection on both cores, detection, and normal traffic before/after | At least 600 s (long) |
| `ipc-backpressure-1h` | Continuous bidirectional traffic for 3,600 s and final counter closure | 3,610 s |
| `m55-restart` | Initial M55 start plus ten normal restarts; 1,000 messages each direction per session | At least 600 s (long) |
| `m55-ready-timeout` | Halt M55 before READY; detect timeout and isolate it | At least 600 s (long) |
| `m55-heartbeat-stop` | Halt M55 after ten heartbeat publications; detect stalled heartbeat and isolate it | At least 600 s (long) |
| `m55-ready-recovery` | READY timeout, isolation and one new session with 1,000 messages each way | At least 600 s (long) |
| `m55-heartbeat-recovery` | Heartbeat stop, isolation and one new session with 1,000 messages each way | At least 600 s (long) |
| `m55-ipc-stall-recovery` | Recover stalled IPC with a live heartbeat | At least 600 s (long) |
| `m55-quiesce-recovery` | Recover after a QUIESCE timeout | At least 600 s (long) |
| `m55-fatal-recovery` | Recover a readable fatal publication | At least 600 s (long) |
| `m55-fatal-unreadable-recovery` | Recover heartbeat timeout after a lost fatal publication | At least 600 s (long) |
| `m55-repark-failure` | Reject REPARK, remain isolated, deny retry | At least 600 s (long) |
| `m55-load-failure` | Reject loading, remain isolated, deny retry | At least 600 s (long) |
| `m55-recovery-ready-failure` | Replacement READY timeout, containment and denied retry | At least 600 s (long) |

For sequential and fault-injection profiles, 600 seconds is a heartbeat observation endpoint, not a required message-phase duration. Backpressure profiles include ten additional heartbeat seconds after messages stop. Read acceptance parameters from that package's `layout.json`.

For `m55-restart`, use the [restart contract](m55-restart.md) and its packaged `analyze_dual_restart.py`. The run must contain 11 complete sessions and the selected observation scope. Hardware evidence belongs to the matching image and its separate validation report.

For example, build fault injection in its own directory:

```sh
BES_TEST_PROFILE=ipc-fault-injection
.venv/bin/python -m west build --sysbuild -p always \
  -b bes2700yp_devkit/bes2700yp/bth \
  bestechnic-zephyr/apps/bes2700yp/bth \
  -d "build/bes2700yp/$BES_TEST_PROFILE" -- \
  -DZEPHYR_TOOLCHAIN_VARIANT=cross-compile \
  -DCROSS_COMPILE="${CROSS_COMPILE:?Set up the toolchain first}" \
  -DBES_VALIDATION_PROFILE="$BES_TEST_PROFILE"
```

`-p always` clears the selected build directory. Save any package and validation evidence you need before rebuilding.

## Hardware validation

### Preserve the package

Save the complete `release/` directory for each candidate, and use the same copy for flashing, parsing, and review. This example names an ordinary-build candidate with UTC time and the first 12 image SHA256 digits:

```sh
BES_CANDIDATE="main-$(date -u +%Y%m%dT%H%M%SZ)-$(sha256sum build/bes2700yp/main/release/zephyr.bin | cut -c1-12)"
BES_TEST_DIR="validation/$BES_CANDIDATE"
mkdir -p validation
(
  mkdir "$BES_TEST_DIR" || exit 1
  cp -a build/bes2700yp/main/release "$BES_TEST_DIR/release" || exit 1
  cd "$BES_TEST_DIR/release" || exit 1
  sha256sum -c SHA256SUMS
)
```

Continue only if every entry is `OK` and the command exits 0. The candidate directory must be new. For another profile or build, make a new candidate from its build directory. In a new terminal, restore `BES_TEST_DIR` to the saved location.

### Flash and capture

1. Use official BES **DldProductLine** to flash `$BES_TEST_DIR/release/zephyr.bin`, following [board flashing requirements](getting-started.md#flashing-requirements).
2. Configure the serial tool for 1152000 baud, 8N1, no hardware/software flow control; see [serial settings](hardware/bes2700yp.md#serial-and-logging). Save raw output without host timestamps, line prefixes, filtering, or edits.
3. Start capture before boot. Record board model/revision, SHA256 of the flashed file, operation time, and boot method. Distinguish power cycles from resets.
4. Save the first full run as `$BES_TEST_DIR/run-01.log`, from boot through final message and dual-core results. Preserve complete failure logs.

BTH normally reports both cores. A trailing `pass` line alone is insufficient; the analyzer checks identity, timing, heartbeats, messages, and order. Read `observation` and `duration_seconds` in the candidate's `layout.json`. Capture through the result for the planned scope; message completion alone is insufficient. The default analyzer scope is long.

### Analyze results

The two isolation profiles use packaged `analyze_dual_isolation.py`; see the [fault isolation contract](m55-restart.md#fault-isolation-profiles). They keep M55 held in reset and do not reload it.

Recovery profiles use packaged `analyze_dual_recovery.py`; see [one-attempt recovery](m55-restart.md#one-attempt-fault-recovery). The recovered session completes messages and normal shutdown before BTH finishes its observation.

For the four message profiles, the packaged `analyze_dual_message.py` checks boot, timing, heartbeats, and messages together. For `m55-restart`, use packaged `analyze_dual_restart.py` with the same `--manifest` and `--output` arguments. Keep the full package because analyzers import companion files; use the versions matching the flashed image:

```sh
.venv/bin/python "$BES_TEST_DIR/release/analyze_dual_message.py" \
  "$BES_TEST_DIR/run-01.log" \
  --manifest "$BES_TEST_DIR/release/layout.json" \
  --output "$BES_TEST_DIR/run-01.json"
```

Here `--manifest` takes **`layout.json`**, not `manifest.json`. It checks BTH/M55 build, profile, pair, and IPC parameters. Exit codes are:

| Status | Exit | Meaning |
|---|---:|---|
| `pass` | 0 | Boot session meets parsing rules |
| `fail` | 1 | Error or contract violation |
| `incomplete` | 2 | Evidence needed for acceptance is missing |

Top-level `status` describes only the last boot session. Inspect `session_count` and every session's `status`, `errors`, and `missing`; a later pass cannot erase an earlier failure. Save each run separately. A one-run report should have one passing session with empty `errors` and `missing`; review any timing warnings.

Freeze the required profiles, scopes and cold-boot counts before hardware
validation, using the observation matrix below and the change's impact.
Run counts may increase for failures or changed shared paths. Each run belongs
to its image SHA256 and package. Record physical power removal separately;
a parser cannot prove it, and earlier firmware reports do not validate changed bytes.

### Observation scopes

The package's `observation` contract defines the supported scopes. The twelve
lifecycle profiles, `ipc-sequential`, and `ipc-fault-injection` produce three
results from the same image and boot:

- `functional`: all scenario operations and message counts have completed.
- `short`: another 60 seconds have elapsed after functional completion, with
  continuous healthy samples and a fresh terminal-state check.
- `long`: monitoring has reached both 600 seconds from monitor start and the
  complete short window, followed by another terminal-state check.

Lifecycle checkpoints confirm local-worker idle, M55 reset held and clear
mailbox channel-1 flags without accessing held-reset DTCM. Message checkpoints
reread both live queue publications, guards and empty-ring state; M55 heartbeats
continue. Ten normal restarts, message targets and all eleven protocol error
cases remain required. Sample counts follow elapsed time, not a fixed 61 rows.

Use the same packaged scenario analyzer, explicitly selecting a short scope:

```sh
.venv/bin/python "$BES_TEST_DIR/release/analyze_dual_recovery.py" \
  "$BES_TEST_DIR/run-01.log" --manifest "$BES_TEST_DIR/release/layout.json" \
  --scope short --output "$BES_TEST_DIR/run-01-short.json"
```

Use this example for a recovery profile; choose the corresponding message,
isolation or restart analyzer for other profiles. Omitting `--scope` selects
`long`. `--scope functional` is useful for diagnostics but does not complete a
short cold-boot check. `zephyr_observe result` has `scope=1` for short and
`scope=2` for long. A result line alone never proves acceptance.

Reports distinguish `requested_scope`, `scopes`, `overall_status` and `complete`.
A short `status: pass` may coexist with `overall_status: incomplete` and
`complete: false`. Continue capture when testing long; the firmware does not
stop at short success. Later errors in the same boot invalidate the run even
when parsing with `--scope short`. Preserve the complete available capture;
do not cut a later failure off a passing prefix.

Both backpressure profiles support only long scope and retain their 600/3600
seconds of active traffic plus ten seconds for observation and completion.
Older packages retain their own analyzers and full-duration rules; adding a
CLI option cannot grant an old image short acceptance.

A representative milestone matrix runs all sixteen scenarios once. Keep long
scope for `m55-ipc-stall-recovery`, `m55-recovery-ready-failure` and
`ipc-sequential`, along with both full backpressure profiles; use short scope
for the other eleven. Extra IPC/QUIESCE cold boots may use short scope. Record
scope and repetitions explicitly. Clock, timer, reset or IRQ changes and any
unexplained failures require additional long checks for affected paths;
60-second observation is not equivalent to 600-second reliability coverage.

### Evidence records

For each run, retain raw serial logs, parser reports, board identity, and boot-method records linked by image SHA256 to the complete candidate package. Summarize profiles, run counts, results, and incomplete checks. Keep evidence outside build directories.

The package's `hardware: not_tested` reflects its state at packaging time. Record later hardware tests separately without rewriting the package manifest or checksums. A new image needs a new test record.

## Maintainer checks

These tools check dependency propagation and isolation, not flashing or hardware behavior.

### Incremental builds

[tests/verify_incremental.py](../tests/verify_incremental.py) checks whether BTH, M55, and HAL edits trigger rebuilding and whether corrupt HAL bytes are rejected. It temporarily changes source and HAL files; run only in dedicated integration and HAL copies with no concurrent edits, using a new build directory:

```sh
.venv/bin/python bestechnic-zephyr/tests/verify_incremental.py \
  --workspace . --build-dir build/verify-incremental \
  --cross-compile "${CROSS_COMPILE:?Set up the toolchain first}"
```

Inspect `build/verify-incremental/incremental-evidence/report.json` for `status: pass`, `changes_restored: true`, and both worktree states. Hardware testing uses the saved candidate instead.

### Isolated build

[scripts/isolate_build.py](../scripts/isolate_build.py) requires bubblewrap and working unprivileged user namespaces. It hides external directories and network, builds twice in a read-only workspace, and compares image SHA256. Set `BES_SDK_DIR` to the absolute SDK directory outside the workspace that should be hidden. The toolchain can use the [default location](getting-started.md#install-the-toolchain), but must not be inside that SDK directory. Fetch blobs before isolation; venv, Git metadata, and symlinks must be usable inside the sandbox.

```sh
.venv/bin/python bestechnic-zephyr/scripts/isolate_build.py \
  --workspace . --output build/verify-isolation \
  --cross-compile "${CROSS_COMPILE:?Set up the toolchain first}" \
  --sdk "${BES_SDK_DIR:?Set BES_SDK_DIR to the SDK directory to hide}"
```

The output directory must be new; logs and `isolation-report.json` appear there. If an ordinary build with the same inputs and `ipc-backpressure` profile already exists, add `--reference-build build/bes2700yp/main` (adjust path as needed). The script compares identities and requires the ordinary and two isolated `zephyr.bin` files to match exactly, detecting effects such as different toolchain installation paths.
