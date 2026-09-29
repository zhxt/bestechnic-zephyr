# Bestechnic HAL Module

[简体中文](hal.zh-CN.md)

`hal_bestechnic` supplies prebuilt HAL libraries, a public interface header, and a linker script for the BES2700YP Zephyr integration. Bootstrap links the libraries for early hardware initialization and retains service entry points for BTH. The BTH and M55 Zephyr images do not link the HAL libraries directly; see [architecture](architecture.md#hal-and-hardware-service-boundary).

## Read-only resource service

The [resource ABI](../include/bestechnic/bes2700yp/bes2700yp_resources.h) exposes
system snapshots through the resident BTH bootstrap. BTH applications use
`bes_resource_read()`; neither Zephyr core links the vendor HAL directly.
This descriptor offers only the system-snapshot capability. UART readback uses
the separate descriptor below; neither descriptor grants resource writes or voltage control.

Discovery uses operation 9 of the existing 32-byte dual service, independently
of M55 preparation. The returned 32-byte descriptor resides in read-only Flash;
its data address and Thumb execution entry are validated separately. The ABI
uses fixed-width integer fields, a 96-byte request and a 64-byte snapshot.
The entire aligned request must lie in BTH application RAM
`[0x20540000, 0x2055c000)`, outside the diagnostic page and M55 memory.
Reserved fields must be zero. The final ELF audit checks the descriptor,
file-backed executable callees, integer-only dispatch and a 256-byte stack
budget for the service call chain, excluding exception frames and the caller.

`bes_resource_connect()` runs once in `PRE_KERNEL_1` at priority 0. The early
snapshot is retained until application validation can print it. Privileged
BTH early/thread callers may read snapshots; interrupt and unprivileged
contexts are rejected. A short interrupt-masked read excludes BTH lifecycle
preemption and restores PRIMASK. There is no wait, logging or hardware write
in the service. Hardware can still evolve between register reads, so this is
not an atomic snapshot of independently running hardware.

Before the peer has been parked, only the lifecycle phase is valid; hardware
fields are zero and their validity bits are clear. In parked, released and
reset-held states, existing HAL register readback and the 24 MHz configuration
check are available. That check describes configured clock sources, not an
external frequency measurement. Missing validity bits mean unavailable data,
not a successful zero-valued read. No M55 TCM access is needed while reset is held.

The wire protocol defines its own signed statuses. The client maps malformed
requests to `-EINVAL`, unsupported ABI/operations/resources to `-ENOTSUP`,
invalid execution context to `-EPERM`, lifecycle contention to `-EBUSY`, an unconnected client to `-ENODEV`, and
an invalid response to `-EIO`. On failure the caller must discard the output.
Future state-changing operations require the arbitration contract below;
they are not implied by the read-only capability.

## UART0 read-only resource service

The [UART resource ABI](../include/bestechnic/bes2700yp/bes2700yp_uart_resources.h)
uses discovery operation 9 with argument 2. It has its own ABI 2 descriptor,
capability 2, 96-byte request and 64-byte snapshot. Discovery argument 1 retains
the system ABI 1 descriptor and capability unchanged; a system descriptor cannot
be accepted as a UART descriptor. Missing UART support returns an explicit error.

`bes_uart_resource_connect()` and the early UART snapshot run in the same first
PRE_KERNEL_1 initializer. `bes_uart_resource_read()` accepts only privileged BTH
early/thread calls through the bounded bootstrap bridge. The bridge restores
PRIMASK, rejects invalid request spans before dereferencing them, and reports
changing hardware samples as `-EBUSY`. No resource configuration is written.

The HAL reads BTH CMU UART0 source/divider, peripheral and functional gates and
reset release, plus AON P2_2/P2_3 mux/pull. Two masked configuration samples must
match. They detect observed changes, not ABA or a globally atomic snapshot; this
profile requires sole BTH configuration ownership. No MEMSC lock or vendor
IOMUX setter is called. Only BTH/AON registers prepared before Zephyr are read,
including when the M55 domain is unavailable.

Snapshot validity bit 0 denotes configured input frequency, bit 1 gate/reset
readback and bit 2 the digital AON pad route. Source 1 is crystal, 2 crystal x2,
3 PLL; PLL divider is reported but its frequency remains unavailable. A disabled
clock gate is distinct from an unknown source frequency. Frequency derives from
register selection and the HAL reference-source metadata, not external measurement.
Gate/reset bit 0 refers to the peripheral bus and bit 1 to the functional block.
Pin IDs are bank*8+index; pull bit 0 is RX and bit 1 TX. Unknown routes retain raw
mux/pull values without setting pin-route validity. Connector wiring and voltage
are separate board facts.

The applications check UART readback alongside every existing system resource
probe. The manifest requires matching UART records at early/released phases and,
for lifecycle profiles, the final reset-held phase. Missing, malformed, changed
or incompatible records invalidate acceptance. UART output ownership is unchanged.

## BTH lifecycle arbitration

The resident [arbitrator](../platforms/bes2700yp/boot/bootstrap/arbitration.c)
serializes PREPARE, PARK, RELEASE, STOP, REPARK and reset confirmation. It accepts
privileged BTH threads with PRIMASK clear; ISR, unprivileged and interrupt-masked
mutation calls return wire status `-14`. Ownership is acquired once, before phase
validation, with no spin or kernel wait. A competing ordinary operation returns
`-12` (BUSY). Short state critical sections restore PRIMASK; interrupts remain
enabled during the existing HAL operation. Ownership ends within that service
call, before the caller's IPC, loading, logging or scheduling waits.

A competing STOP at phase 2 or later latches a pending isolation request and
returns BUSY, not success. The active owner performs containment before releasing
ownership; STOP requests during that attempt coalesce. Successful containment
cancels an otherwise successful non-STOP operation with `-13`. Existing operation
errors take precedence, and phase 5 remains faulted. A failed reset never permits
REPARK or reports confirmed isolation. The requester must allow the owner to run
and inspect the resulting state; repeatedly spinning on BUSY would defeat this
thread contract. The guard adds no polling. It does not establish a deadline for
all existing HAL calls or recover an owner that cannot execute.

System ABI 1 and UART ABI 2 retain their descriptor, request, successful snapshot
and capability layouts. Both reject reads during lifecycle ownership with wire
status `-4`, without touching hardware or output fields. Current clients map it
to `-EBUSY`; older system clients reject that unknown status as `-EIO`. This is an
explicit error extension, not a new successful snapshot shape. UART's existing
changing-sample BUSY result has the same meaning to callers: discard the output.
Discovery and early reads remain available before PREPARE.

[Arbitration diagnostics](../include/bestechnic/bes2700yp/bes2700yp_arbitration.h)
use discovery argument 3, independent ABI 3, capability 4, a 32-byte descriptor,
a 96-byte request and a 64-byte read-only snapshot. `bes_arbitration_read()`
reports phase, owner operation, pending STOP, entry/exit and BUSY counts, deferred
STOP requests/completed attempts, last operation/result, and probe counters.
Counters are unsigned 32-bit values; `last_rc` encodes a signed wire result in
32 bits. The snapshot is taken under a restored local mask and is available even
while an owner is active. No begin/end, configuration write or lock release is
exported. State resides in bootstrap-owned BTH SRAM, not a shared diagnostic gap.

BTH validation logs `zephyr_arbitration snapshot` beside system/UART records;
acceptance requires zero owner/pending and balanced entry/exit counters. The
`resource-arbitration` profile injects deterministic same-core nested requests at
a confirmed STOP boundary. It checks ordinary BUSY, deferred STOP, malformed and
unsupported requests, and read rejection while owned. Its five checks produce
`probe_mask=31`, one probe run, two mutation BUSY results and one completed deferred
STOP. Other profiles require zero injection counters. Host tests additionally
interleave STOP during RELEASE and failed reset. These are software reentry
checks, not measurements of cross-master hardware contention.

This BTH mechanism supplies neither MEMSC locking nor clock/reset/pinctrl/GPIO
configuration APIs. UART0 and its pads stay reserved, and the trusted M55 firmware
must obey the existing ownership contract. Hardware enforcement and independent
bus masters are outside this software guard.

## Runtime resource interface design

This section specifies the resource-service design. Available APIs and drivers
are defined by the public headers and [supported features](hardware/bes2700yp.md#supported-features).
The design covers BTH UART0 and explicitly assigned GPIO resources; GPIO use
requires an identified instance and confirmed board wiring. M55 does not gain
direct access to the BTH library or shared CMU/PSC/PMU/IOMUX through this design.

### Resource operations

Operation names below describe responsibilities, not exported C symbols.
Use project resource IDs for reviewed instances; never expose
vendor enumeration values, arbitrary register addresses or unrestricted masks.

| Operation | Required behavior | Access boundary |
|---|---|---|
| Capability query and snapshot | Report available operations and valid clock/gate/reset/pin fields without changing hardware | Retained bridge discovery and explicitly valid fields |
| UART input-rate query | Decode the selected source/divider; validate the expected rate | A HAL facade with register-backed readback; a constant alone does not establish the current rate |
| Peripheral gate on/off | Operate only reviewed leaf gates and check their resulting state | Restricted facade, ownership checks and bounded access; UART0 remains on while serving logs |
| Peripheral reset assert/deassert/status | Affect only the owned instance after its users stop | Restricted facade with readback; active logging UART, M55 CPU and shared domains are not general reset targets |
| Pin state query/apply | Validate the whole group, owner and dependencies; read back mux/pull fields | Real readback and bounded hardware-lock handling; preserve unrelated fields and account for chip revision |
| GPIO data and IRQ | Operate an assigned instance through a Zephyr driver | Confirmed register semantics, pad mapping, clock/reset and interrupt routing; data and IRQ paths stay in the driver |

Hardware readback must reflect actual registers. A successful configuration call
does not establish a digital pad's electrical level; record that separately from
the board definition and measurements. Hardware-lock waits must be bounded in the
backend itself, rather than timed only after an unbounded call returns.

Keep voltage switching, root-clock changes, DVFS, domain power-off, M55 reset,
RAM remapping and release of bootstrap timer/mailbox reservations outside the
resource interface defined here. A valid unsupported operation returns an explicit error.
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
request that reports completion before the gate is off. An operation that cannot
meet this contract remains unsupported. Sleepable setup may have a separate bounded
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

### UART ownership

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

Each resource grant needs a legal-use test and a conflict test. GPIO reset/gating
must account for other users of the same bank. Default pin configuration does not
grant sleep-state or system-PM capabilities. [Architecture](architecture.md#resource-service-extension-design)
defines the bridge and ABI; [testing](testing.md) defines validation evidence.

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
