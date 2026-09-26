# M55 normal restart with retained RAM

[简体中文](m55-restart.zh-CN.md)

The `m55-restart` validation profile starts both Zephyr images, then stops and
restarts only the M55 CPU ten times. BTH stays running for 600 seconds. The
initial start and ten restarts produce 11 sessions; each session exchanges
1,000 messages in each direction with payload lengths from 0 through 96 bytes.
The operation retains RAM, clocks and power. It validates a cooperative normal
restart; it does not implement forced recovery after an unresponsive peer.

## Build and acceptance

Use the [build instructions](getting-started.md) with
`BES_VALIDATION_PROFILE=m55-restart` and a separate build directory. The final
image remains `zephyr.bin`. Analyze a full boot capture with the matching
frozen package:

```sh
python release/analyze_dual_restart.py current_boot.cap \
  --manifest release/layout.json --output analysis.json
```

The analyzer requires 11 READY records, 22 endpoint records, 11 healthy peer
snapshots, 11 reset hardware snapshots and 11 session results. It also checks
22 reset timer diagnostics (RELEASE and STOP for each session), ten REPARK
records, 601 BTH heartbeat samples, message accounting, and final guards.
Each direction must have `sent=acked=peer handled=1000`; unexpected rejections,
protocol errors and spurious mailbox interrupts must remain zero. Analyzer
exit codes 0, 1 and 2 mean pass, fail and incomplete respectively.

The first board check should confirm that session 2 starts after the first
M55 stop. After one complete 11-session and 600-second run, repeat with two
independent physical power cycles. Rerun affected message profiles when shared
startup, mailbox or worker behavior changes. The result belongs to the exact
image SHA256 and package; previous R1 hardware reports do not validate this
new candidate.

## Lifecycle ownership

The BTH manager in `platforms/bes2700yp/lifecycle/` owns session state, peer
stop, M55 image loading and CPU release. `platforms/bes2700yp/resources.json`
defines the shared-memory regions and time budgets. The bootstrap exposes a
bounded hardware service through the public HAL interface. Only the manager
may assert M55 CPU reset after local mailbox access is stopped and the peer's
last shared-memory writer has exited.

A normal stop drains messages, disables the local worker, waits for the peer to
be idle, asserts and reads back CPU reset, and clears mailbox channel 1.
Channel 0 remains available. A failure to confirm reset enters FAULT and
prevents REPARK. A failed channel clear leaves sends disabled and prevents
resume. READY, message exchange and QUIESCE have 5, 30 and 5 second limits.
No operation turns off M55 RAM or its power domain.

The restart control block occupies `0x2015e280..0x2015e300`. Each core owns
64 bytes with a session identity and guard. Both device trees reserve the
region. The offline audit checks the declarations and the file-backed and
zero-initialized ELF ranges. Restart uses a separate control ABI while the
four message profiles keep their original shared-memory ABI.

## Reset and service checks

The reset wait and sampling functions execute from bootstrap SRAM. They use
the BTH 6 MHz timer, a 10 ms budget after the first valid sample, and at most
1,024 polls. Each sample takes at most 32 attempts to obtain two coherent
timer reads. Only those two reads briefly mask normal interrupts; the prior
PRIMASK value is restored. The sampler is prevented from being inlined or
calling an external function. Failed sampling leaves M55 held in reset.

Reset diagnostics have a dedicated 80-byte region at
`0x2055c1a0..0x2055c1f0`. Each call clears it first. A record is valid only
after entering the reset wait, so an early service rejection cannot reuse an
older record. The report includes the operation, service return, reason,
sampling attempts, elapsed ticks, reset register values and sampler address.
The analyzer checks the values and matches the sampler address to this
package's ELF.

Message and restart profiles use the same service-entry contract. The host
audit checks the actual bootstrap service address, its executable segment and
the BTH call site. An executable Flash alias in
`0x14000000..0x14800000` is accepted alongside the existing SRAM service
window; the download view beginning at `0x34000000` is not an execution
address. Entry failures include a precheck record with the failing service or
CPU-state fields.

## Prepare PARK while M55 remains in reset

After the first session, each subsequent restart has one REPARK record between
its stop and release steps. The M55 DTCM window must not be accessed while the
CPU is held in reset. Bootstrap calls
`bes2700yp_m55_repark_prepare()` instead. The API temporarily switches only
physical RAM bank 9 (`SYS_RAM_SEL0` mask `0x38000000`) to AXI, writes and
verifies the three PARK words at `0x20320000`, `0x20320004` and `0x20330000`,
then restores and verifies the original selector. The expected words are
`0x2015ffe0`, `0x200c0009` and `0xe7fdbf30`. CPU release remains a separate
operation after successful preparation.

The caller must own the mapping exclusively: both cores' other accessors are
quiet, cache is disabled, and the current BES2700YP memory layout is in use.
Each selector readback is bounded to 32 attempts. Mapping or word failures
still attempt to restore the original selector; any error enters FAULT and
prevents release. The 100-byte REPARK diagnostic region is
`0x2055c800..0x2055c864`. It records reset state, selector values, physical
addresses, expected and read-back words, restoration and write mask. A
successful record must still show the M55 CPU held in reset.

Host tests exercise the actual HAL C implementation, including failed
readback and restoration, memory preservation and interrupt-state restoration.
ELF audit verifies the SRAM placement and service call path. Board tests remain
necessary to validate physical mapping, register synchronization and IRQ
timing. See the [test guide](testing.md) for the package and log workflow.
