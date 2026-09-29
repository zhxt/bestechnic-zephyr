# Restricted GPIO qualification

[简体中文](gpio.zh-CN.md)

Two optional sysbuild profiles exercise a small BTH-owned GPIO path alongside
normal dual-core IPC. They use a bootstrap service backed by an original HAL
facade. They do not register a Zephyr GPIO or pinctrl controller, configure GPIO
interrupts, or transfer shared hardware ownership to M55.

| Profile | Inputs | Output | Default state |
|---|---|---|---|
| `gpio-input` | P2_0 and P2_1, internal pull-up, active low | None; P1_4/P1_5 unchanged | Optional; disabled in ordinary profiles |
| `gpio-led` | Same two inputs | P1_4, active low; preload high before output enable | Optional; requires electrical confirmation |

These mappings correspond to S3/S4 and D2 on the BES27001.2 reference schematic.
D3 on P1_5 is left unchanged as a control. Similar appearance is insufficient to
establish the wiring or voltage of another board. Confirm the physical switch
and LED connections on the actual board. P2_2/P2_3 remain reserved for UART;
power and reset buttons are not test inputs.

Before using the output profile, measure module VIO and the supply ends of the
D2/D3 series resistors. Check input limits and LED current against the actual
module/board documentation. The service does not change voltage selection or
pad drive strength. Register readback cannot prove electrical compatibility or
visible LED operation. The input profile does not change LED mux, pulls,
direction or output latch, so an initially lit LED can remain lit.

## Build and exercise

Use the [normal sysbuild command](getting-started.md), adding
`-DBES_VALIDATION_PROFILE=gpio-input` or `-DBES_VALIDATION_PROFILE=gpio-led`.
Give each profile a separate build directory. Flash the full `zephyr.bin` and
capture the complete boot and application logs at the documented baud rate.

1. Start with `gpio-input` and physically power-cycle the board. Wait for
   `zephyr_gpio waiting` before operating switches.
2. Press and release each input at least ten times, in any order. Hold each
   pressed and released state for about half a second. The app polls every
   10 ms and requires 50 ms of stable level. A button held at boot is not a
   counted press; first release it to arm counting. The interaction deadline
   is five minutes.
3. For `gpio-led`, repeat the inputs. P1_4 starts high (LED off), alternates
   low/high once per second for ten complete flashes, then stays high. Observe
   D2 and check that D3 keeps its original state. The app also reads the pad
   level, with at least 10 ms settling after each change.
4. Both keys must finish released. After GPIO and sequential IPC checks finish,
   the log emits `zephyr_gpio result ... pass=1` followed by
   `zephyr_observe functional`. Wait for
   `zephyr_observe result version=1 scope=1 pass=1` to complete the following
   60-second health window. The same image can continue to its long checkpoint;
   a short pass is not a long-duration result.

Analyze with the script and layout.json from the same source/image:

```sh
.venv/bin/python bestechnic-zephyr/scripts/analyze_dual_message.py capture.cap \
  --manifest build/gpio-input/release/layout.json --scope short \
  --output build/gpio-input-analysis.json
```

Substitute the output profile's directory when analyzing that image. The parser
checks boot identity, IPC, GPIO records and observation coverage together. A
GPIO result alone is not complete acceptance. Record physical power cycles,
measured voltage and visible LED behavior alongside the image SHA256; the
serial log cannot establish those facts. A missing interaction deadline is an
incomplete user exercise, not by itself evidence of faulty GPIO hardware.

## Interface and ownership

Discovery operation 9 with argument 4 returns a 32-byte descriptor with ABI 4,
capability 8 (input/read) or 24 (input/read and output). Existing service ABIs
retain their meanings. The [contract](../include/bestechnic/bes2700yp/bes2700yp_gpio.h)
uses a 96-byte request containing a 64-byte snapshot. The snapshot contains
phase, latched fault, candidate pad levels/direction/latches, full P1/P2 mux and
pull registers, AON clock/reset status, and GPIO IRQ/control state.

| Operation | Allowed request | Wire return errors |
|---|---|---|
| 1 read | pin=0, value=0 | -1 invalid; -2 unsupported; -3 context; -4 busy; -5 unavailable; -6 fault |
| 2 input | pin=16 or 17, value=0 | Same |
| 3 output | pin=12, value=0 or 1; output profile only | Same |
| 4 write | pin=12 already configured as output, value=0 or 1 | Same |

Calls require a privileged BTH thread with interrupts initially enabled. Writes
hold the lifecycle arbitration guard, mask local interrupts, recheck phase
(live or isolated), then try AON MEMSC0 once. Busy returns without waiting.
Read calls use the same short interrupt exclusion and hardware semaphore; they
do not increment lifecycle write counters. M55, ISR, unprivileged and already
IRQ-masked calls are outside the API contract.

The bank must already be clocked and out of reset. The service never resets the
bank, changes its gates, enables an interrupt, or modifies pin voltage. Input
configuration masks only the requested mux/pull bits. Output configuration first
disables that pin's output, preloads its latch, applies mux/pulls, then enables
output. Active IRQ or hardware-control ownership on that pin is rejected.
Readback failure leaves that pin as input and latches a service fault; further
writes fail until reboot, while readback remains available. This is containment,
not transactional restoration of earlier pin configuration.

The application compares non-target register fields with its initial snapshot.
ELF audits check descriptor/capability consistency, bounded integer-only HAL
calls and stack budget. Host tests exercise the actual service, client, debounce
and HAL mask operations, including negative and parser mutation cases. These
checks supplement board testing and do not establish GPIO IRQ routing or a
complete Zephyr GPIO driver.
