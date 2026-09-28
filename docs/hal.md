# Bestechnic HAL Module

[简体中文](hal.zh-CN.md)

`hal_bestechnic` supplies prebuilt HAL libraries, a public interface header, and a linker script for the BES2700YP Zephyr integration. Bootstrap links the libraries for early hardware initialization and retains service entry points for BTH. The BTH and M55 Zephyr images do not link the HAL libraries directly; see [architecture](architecture.md#hal-and-hardware-service-boundary).

## Runtime resource interface design

This section defines the implementation boundary for resource services; it does
not declare additional APIs or drivers available. The public HAL header remains
a bootstrap interface. The first runtime consumer is BTH UART0; GPIO resources
need an identified instance and confirmed board wiring. M55 does not gain direct
access to the BTH library or shared CMU/PSC/PMU/IOMUX through this design.

### Minimum operations and HAL gaps

Operation names below describe responsibilities, not assigned ABI numbers or
exported C symbols. Use project resource IDs for reviewed instances; never expose
vendor enumeration values, arbitrary register addresses or unrestricted masks.

| Operation | Required behavior | Implementation prerequisite |
|---|---|---|
| Capability query and snapshot | Report available operations and valid clock/gate/reset/pin fields without changing hardware | Retained bridge discovery and explicitly valid fields; existing clock checks and snapshots cover only part of this state |
| UART input-rate query | Decode the selected source/divider; validate the expected rate | A HAL facade with register-backed readback; a constant alone does not establish the current rate |
| Peripheral gate on/off | Operate only reviewed leaf gates and check their resulting state | Restricted facade, ownership checks and bounded access; UART0 remains on while serving logs |
| Peripheral reset assert/deassert/status | Affect only the owned instance after its users stop | Restricted facade with readback; active logging UART, M55 CPU and shared domains are not general reset targets |
| Pin state query/apply | Validate the whole group, owner and dependencies; read back mux/pull fields | Real readback and bounded hardware-lock handling; preserve unrelated fields and account for chip revision |
| GPIO data and IRQ | Support one confirmed instance through a Zephyr driver | Register semantics, pad mapping, clock/reset and interrupt routing review; a vendor header alone is insufficient |

CMU gate/reset primitives exist in the HAL library but are not a supported public
runtime resource ABI. Pin-function readback currently returns a placeholder;
UART voltage setters do not implement switching, and a successful generic voltage
call does not establish a digital pad's electrical level. IOMUX locking contains
an unbounded hardware-lock wait under a local interrupt mask. These paths require
reviewed implementations before runtime use, not a wrapper that merely forwards
their return values. GPIO direction/IRQ setup implementations are absent from the
delivered libraries even though vendor declarations exist.

Keep voltage switching, root-clock changes, DVFS, domain power-off, M55 reset,
RAM remapping and release of bootstrap timer/mailbox reservations outside the
initial resource API. A valid unsupported operation returns an explicit error.
Do not introduce a successful no-op to satisfy a Zephyr interface.

### Calling context and failure contract

Resource discovery must work before UART device initialization and before M55
PREPARE. Use a single-owner initialization path before the scheduler; do not take
a kernel mutex there. After startup, resource state changes and M55 lifecycle
hardware operations share one BTH arbitration mechanism. Acquire it before any
overlapping register changes, release it between lifecycle waits, and do not hold
it while waiting for IPC, UART traffic, callbacks or a log lock. Log diagnostics
after releasing it. Short field updates preserve interrupt state; the hardware
backend never sleeps, allocates memory or invokes a Zephyr callback.

Check the pinned Zephyr API's context contract for each adapter. In particular,
`clock_control_off()` is non-blocking and callable from any context. Its supported
path must use a bounded try-acquire and short hardware operation; contention may
fail immediately. Do not implement it using a sleeping mutex or an asynchronous
request that reports completion before the gate is off. Until this can be proved,
leave that operation unsupported. Sleepable setup may have a separate bounded
thread path. Pin reconfiguration and multi-step reset are not ISR operations;
UART/GPIO data and IRQ handling stay in the Zephyr driver.

Define these results consistently at the Zephyr boundary:

| Result | Meaning |
|---|---|
| `0` | Requested postcondition confirmed; query fields carry an explicit validity mask |
| `-EINVAL` | Malformed request, unknown resource ID or invalid pin group; no write |
| `-ENOTSUP` | Valid request outside the implemented capability set; no write |
| `-EPERM` | Reserved resource or wrong owner; no write |
| `-EBUSY` | Arbitration unavailable or another user is active; no write |
| `-EWOULDBLOCK` | Operation requires a calling context unavailable to this caller |
| `-ETIMEDOUT` / `-EIO` | Bounded hardware wait expired / postcondition failed; retain the diagnostic and state of any completed steps |

These are facade/adapter results; vendor positive return codes are translated.
An unimplemented optional Zephyr callback may return the core API's `-ENOSYS`.
Prevalidate complete requests before writing. After a partial failure, restore
only fields whose restoration is known to be safe; otherwise mark that resource
faulted and reject further mutations. Never repair a local failure by resetting
a shared domain. Bound polling by both an audited timebase and an iteration cap
so a stopped timer cannot leave an infinite loop.

### UART adoption and implementation sequence

UART0 begins bootstrap-owned. The intended transition is bootstrap-owned →
adopting → Zephyr-owned, with a fault state for uncertain hardware. Adoption first
checks the inherited rate, pins and gate/reset state without reinitializing them.
Stop normal producers, drain TX with a bound, mask/clear the old IRQ state, then
initialize the driver and transfer ownership. Keep the logging clock enabled.
Failures before any change keep bootstrap ownership; failures after reconfiguration
require verified restoration or fault containment, not an unconditional fallback.

All normal output paths, including helpers in the
[bootstrap contract](../platforms/bes2700yp/boot/bootstrap/bth_contract.h), must
obey the new owner. Enabling Console alone leaves raw UART writers active. Early
output remains bootstrap-owned. Fatal output needs a separate bounded emergency
takeover that masks the UART interrupt and cannot wait on a lock held by the
interrupted writer; preserve a memory diagnostic when serial output is unavailable.
Internal loopback also excludes normal writers and restores external mode before
printing its saved result. It does not establish connector wiring or I/O voltage.

Implement in reviewable steps: discovery and read-only snapshots; bounded HAL
facades; Zephyr resource adapters and exact static grants; UART adoption; then
GPIO input/output, pulls and interrupts. Each grant needs a legal-use test and a
conflict test. GPIO reset/gating must account for other users of the same bank.
First implement a default pin state; sleep states and system PM need their own
contracts. [Architecture](architecture.md#resource-service-extension-design)
defines bridge placement and ABI review; [testing](testing.md) defines evidence.

## Version matching

The integration selects and verifies `modules/hal/bestechnic/` using these files:

| File | Role |
|---|---|
| [west.yml](../west.yml) | Pins the HAL repository, checkout path, and full Git commit |
| [module-lock.json](../module-lock.json) | Records the same module revisions for consistency checks |
| [hal-release.sha256](../hal-release.sha256) | Pins the SHA256 of HAL `manifest.json` |
| HAL `zephyr/module.yml` | Specifies download URLs and SHA256 for the three libraries |
| HAL `manifest.json` | Records chip, profile, ABI, compiler, and hashes of libraries, header, and linker script |

The [repository check](getting-started.md#check-dependencies) expects `status: pass` and `issues: []`. Builds also verify the actual HAL checkout, chip, profile, ABI, and compiler. A changed HAL commit changes build provenance; rebuild and validate the new image according to impact.

## Troubleshooting

| Error or symptom | Action |
|---|---|
| `module-lock.json differs from west.yml` | Use the west manifest and lock from the same integration commit |
| `Module revision mismatch: hal_bestechnic` | Save local HAL work, then sync the module from the workspace using `west.yml` |
| `HAL manifest.json SHA256 differs from hal-release.sha256` | Restore the pinned HAL commit and matching integration files |
| Missing library or checksum mismatch | Run `west blobs fetch hal_bestechnic` from the workspace root |
| `HAL blob metadata differs from manifest.json` or unavailable URL | Check the module revision and publication status; contact maintainers if metadata disagree, rather than bypassing hashes |
| Missing or changed header/linker script | Restore the pinned HAL commit |
| `Unsupported HAL chip/profile/ABI` | Compare the manifest with the integration configuration |
| `compiler differs from the audited HAL producer toolchain` | Install the compiler version required by the manifest; see [toolchain installation](getting-started.md#install-the-toolchain) |

See [setup and build](getting-started.md) for synchronization commands. The checked-out module's `README.md` and `manifest.json` describe its contents and compatibility; `THIRD_PARTY_NOTICES.md` and `distribution.json` describe license and distribution status.
