# Restricted GPIO qualification

[简体中文](gpio.zh-CN.md)

The `gpio-input` and `gpio-led` sysbuild profiles exercise a small BTH-owned GPIO path alongside
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
capability 40 (input/read/sample) or 56 (input/read/sample and output). Existing service ABIs
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
| 5 sample | pin=0, value=0; header, pins and inputs only; other fields zero | Same |

Calls require a privileged BTH thread with interrupts enabled. Every call holds
lifecycle arbitration ownership across preemption; only RAM guard bookkeeping
briefly masks interrupts. Hardware access runs with interrupts enabled. Writes
recheck phase (live or isolated); full reads and writes try AON MEMSC0 once and
return busy without waiting. Sampling checks bank availability and reads pad
levels without MEMSC0 or configuration registers. No ISR may acquire MEMSC0 or
call vendor IOMUX setters. M55, ISR, unprivileged and IRQ-masked callers are
outside the API contract. Capability bit 32 identifies this sampling contract;
clients reject older descriptors that lack it.

The bank must already be clocked and out of reset. The service never resets the
bank, changes its gates, enables an interrupt, or modifies pin voltage. Input
configuration masks only the requested mux/pull bits. Output configuration first
disables that pin's output, preloads its latch, applies mux/pulls, then enables
output. Active IRQ or hardware-control ownership on that pin is rejected.
Readback failure leaves that pin as input and latches a service fault; further
writes fail until reboot, while readback remains available. This is containment,
not transactional restoration of earlier pin configuration.

The application samples inputs every 10 ms and compares full snapshots with its
initial state once per second and after configuration/output operations. The
first LED transition is due after one second; both keys remain interactive until
ten complete cycles each, with a five-minute interaction deadline. Existing
kernel/fast-timer health thresholds are unchanged.

Version 2 `zephyr_gpio timing` records accompany health sample 1 and every tenth
sample, and health failures. They report sample/read/write call counts, maximum
call time in independent fast-timer ticks, entry/exit mask violations, and
SysTick LOAD/VAL/pending state. Call time includes preemption and is not an
IRQ-disabled duration. Diagnostics never read SysTick CTRL/COUNTFLAG, which would
disturb kernel timekeeping. The analyzer requires these records and rejects mask
violations, missing samples and excessive full-snapshot polling.

ELF audits check descriptor/capability consistency, bounded integer-only HAL
calls and stack budget. Host tests exercise the actual service, client, interactive application, debounce
and HAL mask operations, including negative and parser mutation cases. These
checks supplement board testing and do not establish GPIO IRQ routing or a
complete Zephyr GPIO driver.

## Standard Zephyr GPIO API

The `gpio-api-input` and `gpio-api-led-restart` profiles enable
[the BTH GPIO driver](../bsp/drivers/gpio/gpio_bes2700yp.c) with
[the service-backed controller binding](../bsp/dts/bindings/gpio/bestechnic,bes2700yp-gpio.yaml).
The existing HAL and bootstrap service remain the hardware owner. The driver
provides pin configuration, raw port input, masked output, set, clear and toggle.
Zephyr handles logical active-low conversion; raw operations retain physical levels.

| Pin | Supported configuration | API grant |
|---|---|---|
| P2_0 / 16, P2_1 / 17 | `GPIO_INPUT | GPIO_PULL_UP` | Both profiles; only the input profile configures the keys |
| P1_4 / 12 | Push-pull output, optional initial high/low | Output profile only |
| Other pins, including P1_5 and UART pads | Not granted | Reserved in DTS and rejected by the driver |

Direction is restricted per pin. Pull-down, unbiased input, open-drain,
disconnected mode, GPIO IRQs and M55 calls are unsupported. Device initialization
only validates the service descriptor. The application must configure pins after
M55 launch; `device_is_ready()` does not imply the lifecycle phase permits a write.
GPIO hogs and automatic LED/input consumers configured during initialization are
not supported. The board's disabled `gpio-keys` and `gpio-leds` nodes provide DT
specifiers without enabling those consumers.

Calls require a privileged BTH thread with PRIMASK and BASEPRI clear. ISR or
interrupt-masked calls return `-EWOULDBLOCK` without hardware access. A per-device
nonblocking semaphore serializes calls, including output-latch read and write for
toggle. Contention also returns `-EWOULDBLOCK`; applications may retry later in a
thread. No spinlock covers AON register access. Direct service writers must not be
mixed with driver writers. Diagnostic read-only snapshots remain available.
Configure pins from a single application context before concurrent data operations.

Invalid pin/mask requests return `-EINVAL`; unsupported directions, flags and IRQ
configuration return `-ENOTSUP`. Output writes before successful output configuration
return `-EACCES`. Service errors propagate; fault-latched reads return `-EIO`.
A failed port read leaves its output argument unchanged. GPIO clocks/reset must
already be usable; the driver does not change clock gates, resets, voltage or pad
drive strength. It has no separate pinctrl provider.

Select the profile with `-DBES_VALIDATION_PROFILE=<name>` in the regular sysbuild command:

- `gpio-api-input`: wait for `zephyr_gpio waiting`, perform ten press/release cycles
  on each key, then wait for the post-functional 60-second short result. Pad samples
  use `gpio_port_get_raw()` and setup uses `gpio_pin_configure_dt()`. Full service
  snapshots are diagnostics once per second. Analyze with `analyze_dual_message.py`.
- `gpio-api-led-restart`: no key operation is required. D2 is configured inactive
  through `gpio_pin_configure_dt()`, toggled on during each of 11 M55 sessions, and
  set inactive after each stop. Each transition checks actual pad level and configuration,
  including retention before writing again. D3, key and UART configuration remain
  unchanged. After 22 transitions D2 stays off; terminal checks continue each second.
  Analyze with `analyze_dual_restart.py`. Flash only after the electrical checks above.

Both analyzers require the matching release/layout.json and accept `--scope short`.
The output profile emits `zephyr_gpio_api` baseline/checkpoint/observe records in
addition to the complete lifecycle and observation protocol. A short pass requires
all 11 sessions and the following 60 seconds; the observation window does not
replace functional coverage. Longer execution is optional and separately reported.
Physical power cycling, LED appearance and voltage remain external observations.
