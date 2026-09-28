# BES2700YP Hardware and Supported Features

[简体中文](bes2700yp.zh-CN.md)

## Chip resources

This overview is based on the official BES [product page](https://www.bestechnic.com/en/article/78/64.html) and [brief data sheet](https://www.bestechnic.com/Uploads/keditor/file/20241010/20241010185852_50097.pdf). It describes chip resources; the integration's actual support is listed below.

| Category | Publicly described resources |
|---|---|
| Main processor | Arm Cortex-M55 with instruction/data TCM and cache |
| Bluetooth Host (BTH) | STAR-MC1 |
| Sensor Hub | STAR-MC1, sensor engine, BECO NPU |
| Memory | Shared 4 MB SRAM, in-package flash, boot ROM |
| Bluetooth | Dual-mode Bluetooth 5.3, LE Audio |
| Audio | Two DACs, four ADCs, ANC, EQ, and related blocks |
| Interfaces | GPADC, SPI, I²C, UART, I²S, TDM, SPDIF, DMIC, PWM, GPIO, and others |
| Security | Security engine, TRNG, eFuse |
| System | DMA, timers, watchdog, JTAG/SWD, and others |

Total shared SRAM is not the capacity available to either Zephyr kernel; see [runtime memory layout](#runtime-memory-layout). The public summary does not specify flash size, peak clock rate, or peripheral instance counts. Consult the relevant BES documentation for exact part specifications.

## Boards and build targets

The project runs separate Zephyr kernels on the BTH and M55 subsystems:

| Subsystem | Processor | Build target |
|---|---|---|
| BTH | STAR-MC1 | `bes2700yp_devkit/bes2700yp/bth` |
| M55 | Cortex-M55 | `bes2700yp_devkit/bes2700yp/cm55` |

Start sysbuild from BTH to create a complete image; M55 is a child image. Building M55 alone does not create a flashable full image.

STAR-MC1 is BTH's hardware processor name; the current Zephyr port uses a Cortex-M33 target configuration. See [SoC Kconfig](../../bsp/soc/bestechnic/bes2700yp/Kconfig) and [BTH DTS](../../bsp/dts/arm/bestechnic/bes2700yp_bth.dtsi). Hardware identity and software target configuration are distinct.

`bes2700yp_devkit` is a project board-target name, not proof of physical-board compatibility. `V05` in board files is not evidence of a hardware revision. Support is limited to BES2700YP; other BES2700/BES2800 variants need separate adaptation and validation.

The repository does not yet record enough hardware information to infer wiring or flashing setup. Confirm these items from official board materials or the board provider before connecting hardware:

| Item | Information to confirm |
|---|---|
| Board identity | Full model, part number, PCB marking, and revision |
| Power | Connector, voltage, and supply method |
| Serial | Connector location, TX/RX/GND pins, and logic level |
| Download | Connector, connection method, and download-mode procedure |

When adding this information, record the source and applicable board revision. Hardware reports must identify the same board. After confirming wiring and download mode, use the official BES DldProductLine tool as described in [flashing requirements](../getting-started.md#flashing-requirements).

## Supported features

This section describes the current code and default dual-core application on `main`. Implemented behavior does not itself establish hardware validation; check reports for the specific image. The [README summary](../../README.md#current-support) compares public chip resources with integration status.

### Implemented behavior and defaults

| Feature | Implementation | Default application | Limits |
|---|---|---|---|
| Dual-core boot and kernels | Bootstrap starts BTH; BTH loads and starts M55; both use Zephyr threads, timers, and synchronization | Two independent kernels enabled | No Zephyr SMP; matching HAL required |
| Inter-core notification | [Mailbox driver](../../bsp/drivers/mbox/mbox_bes2700.c) exposes Zephyr MBOX API | `CONFIG_MBOX` and `CONFIG_MBOX_BES2700` enabled on both cores | Notification only, not message data; busy repeats coalesce |
| Shared-memory messaging | [Message workers](../../platforms/bes2700yp/ipc/worker.c) exchange data and use mailbox notification | Bidirectional messages enabled | Project-specific protocol; no Zephyr IPC service/RPMsg integration |
| BTH UART | [Driver](../../bsp/drivers/serial/uart_bes2700.c) provides polling and interrupt APIs | Zephyr Serial/Console disabled; bootstrap UART carries logs | Fixed 8N1, bootstrap clock/pin setup; no async/DMA or runtime format API |
| System clock/tick | Zephyr Cortex-M SysTick; HAL configures startup clock | Both cores at 24 MHz, 1000 ticks/s; `CONFIG_TICKLESS_KERNEL=n`, `CONFIG_PM=n` | 24 MHz is a project setting, not peak chip frequency; no DVFS or Zephyr system PM |
| FPU/MPU | [SoC configuration](../../bsp/soc/bestechnic/bes2700yp/Kconfig) declares capability; M55 has [MPU regions](../../bsp/soc/bestechnic/bes2700yp/mpu_regions.c) | Both apps set `CONFIG_FPU=n`, `CONFIG_ARM_MPU=n`, `CONFIG_HW_STACK_PROTECTION=n` | Enabling requires separate runtime validation |
| Runtime memory | DTS/linker scripts specify layout; bootstrap initializes hardware | Uses [current layout](#runtime-memory-layout) | Boot and loading require matching HAL and layout |
| M55 normal restart | Optional `m55-restart` profile retains RAM while BTH stops and restarts only M55 | Disabled in default profile; hardware evidence is recorded per image | Cooperative stop only; see [restart contract](../m55-restart.md) |

Mailbox hardware channel 1 appears as logical Zephyr channel 0; channel 0 is reserved for the vendor loader. See the [binding](../../bsp/dts/bindings/mbox/bestechnic,bes2700-mbox.yaml). Shared-memory protocol moves and checks data; notification count is not message count.

The UART driver supports BTH only. BTH's UART device node and Zephyr Serial/Console are disabled by default on both cores. Seeing logs does not mean that driver or Console is enabled; see [serial and logging](#serial-and-logging).

Optional M55 fault isolation profiles are described in the [isolation contract](../m55-restart.md#fault-isolation-profiles). They are disabled by default and do not reload M55. Hardware results belong to each image report.

Optional `m55-ready-recovery` and `m55-heartbeat-recovery` add one controlled reload and a new message session. See [recovery scope and acceptance](../m55-restart.md#one-attempt-fault-recovery); these profiles are disabled by default and require image-specific board evidence.

### Resources not integrated

This table concerns this repository, regardless of upstream Zephyr subsystem availability:

| Chip resource | Current project scope |
|---|---|
| Bluetooth / LE Audio | No controller/HCI, stack, or audio application integration |
| Audio | No ADC/DAC, I²S/TDM/SPDIF/DMIC, or ANC/EQ path |
| Sensor Hub / BECO NPU | No startup, Zephyr target, or NPU runtime interface |
| Flash read/write | HAL supports boot-time flash operations; no Zephyr flash driver or standard application interface |
| GPIO, I²C, SPI, PWM, GPADC, DMA, watchdog | No corresponding BES2700YP Zephyr drivers |
| Security | No security-engine, TRNG, eFuse, or secure-boot validation; image CRC checks integrity only |

### Configuration and validation evidence

Default applications use [BTH prj.conf](../../apps/bes2700yp/bth/prj.conf) and [M55 prj.conf](../../apps/bes2700yp/m55/prj.conf). Application settings override board defaults: the M55 board enables FPU/MPU, while the current app disables them. For a particular image, inspect `release/bth.config`, `release/m55.config`, and generated DTS.

[Mailbox](../../tests/host/test_mbox_bes2700.py), [UART](../../tests/host/test_uart_bes2700.py), and [message-worker](../../tests/host/test_message_workers.py) host regressions cover modelable behavior. Builds and offline audits check image generation, load layout, and package consistency, not hardware operation. The package records `hardware: not_tested` when built; later reports link actual testing to an image SHA256 without rewriting the original package. See [testing](../testing.md).

## Serial and logging

| Parameter | Setting |
|---|---|
| Baud | `1152000` (1.152 Mbaud) |
| Data bits | 8 |
| Parity | None |
| Stop bits | 1 |
| Flow control | Disable hardware and software flow control |

Bootstrap and the current BTH application emit boot and runtime logs through BTH UART. BTH reads and reports M55 status; a separate M55 serial console is disabled by default. See the [boot contract](../../platforms/bes2700yp/boot/bootstrap/bth_contract.h) and [BTH application](../../apps/bes2700yp/bth/src/main.c). Confirm physical wiring from board documentation, not chip pin-mux source. [Testing](../testing.md#hardware-validation) describes complete log collection.

## Runtime memory layout

These are the principal runtime regions for the current `main` dual-core application; lengths use KiB (1024 bytes):

| Region | Start | Length |
|---|---|---:|
| BTH vectors and code | `0x00510000` | 192 KiB |
| BTH data | `0x20540000` | 112 KiB |
| M55 vectors and code | `0x000a0000` | 256 KiB |
| M55 application data | `0x200c0000` | 624 KiB |
| Shared messaging | `0x2015c000` | 8 KiB |

The [BTH DTS](../../bsp/dts/arm/bestechnic/bes2700yp_bth.dtsi) and [boot contract](../../platforms/bes2700yp/boot/bootstrap/bth_contract.h) define BTH regions. The [base M55 DTS](../../bsp/dts/arm/bestechnic/bes2700yp_cm55.dtsi) provides 632 KiB of data memory; the current [overlay](../../apps/bes2700yp/m55/app.overlay) reduces it to 624 KiB, reserving 8 KiB for shared messages.

Code regions here are runtime memory loaded by the boot process. The board DTS `zephyr,flash` choice is for link layout and does not make these regions physical flash. The table omits some boot, diagnostic, and service reservations; use generated DTS, link results, and `release/offline-validation.json` for the complete allocation. See [offline audit](../architecture.md#offline-audit). These runtime addresses are not flash addresses.

Extended profiles cover stalled IPC, QUIESCE timeout, readable/lost fatal publication and recovery-operation failure; see [extended fault contracts](../m55-restart.md#extended-fault-and-recovery-failure-profiles). Injected software failures do not establish physical hardware-failure acceptance.

## Resource ownership

The current dual-core applications use the following ownership policy. It is a
software access contract, not MPU enforcement or proof of electrical wiring.
Bootstrap initializes shared hardware; BTH manages its subsequent use. M55 owns
its private core peripherals and the fields assigned to its IPC endpoint.

| Resource | Initialization / runtime owner | Access boundary |
|---|---|---|
| BTH and SYS root clocks | Bootstrap HAL / BTH | Keep the configured 24 MHz; peripheral setup must not change a shared parent clock |
| CMU, PSC, PMU and IOMUX | Bootstrap HAL / BTH | M55 has no independent shared clock, power, reset or pinmux authority |
| SysTick and NVIC | Each Zephyr kernel | Private to each core; identical addresses or IRQ numbers across cores do not imply a conflict |
| BTH fast timer at `0x40002000` | Bootstrap HAL / BTH | The 6 MHz counter serves logs and bounded reset checks; keep it running and do not claim it for another driver |
| AON timer | Bootstrap / shared read-only observation | Nominal frequency is not an external calibration; measure the actual timebase before changing clock assumptions |
| BTH UART0 at `0x4000b000` | Bootstrap / BTH logging | Still occupied when its Zephyr DTS node is disabled; Zephyr driver takeover needs an explicit handoff |
| Pads P2_2 and P2_3 | Bootstrap UART RX/TX | Reserved even with Serial/Console disabled; they are chip pads, not connector pin numbers |
| Mailbox hardware channel 1 | Each endpoint | Only the assigned SET/CLR fields are shared; hardware channel 0 remains reserved for the loader |
| M55 CPU reset and retained RAM | BTH lifecycle manager | Hold and confirm CPU reset before reloading or remapping; keep domain power and RAM retained |

The mailbox accesses SYS `[0x500000a0, 0x500000a8)` and BTH
`[0x40000134, 0x4000013c)` on both cores. This explicit field-sharing protocol does
not grant either client ownership of an entire CMU window. Recovery may clear both
endpoints only after the peer is held in reset and local users have stopped.
CPU reset alone does not prove that future DMA or other bus masters are idle.

IRQ identity is `(core, interrupt controller, IRQ)`. Current mailbox RX/TX_DONE
IRQs are BTH 39/37 and M55 41/39, with priority 3. BTH UART0 uses IRQ 17 with
priority 2. Both cores use three priority bits, with 64 BTH and 72 M55 external
IRQs. AON GPIO routing has not been established by this port and must not be
inferred by copying an IRQ number between cores.

### Memory ownership and aliases

Use the [resource contract](../../platforms/bes2700yp/resources.json),
[bootstrap contract](../../platforms/bes2700yp/boot/bootstrap/bth_contract.h),
generated DTS and [existing ELF audit](../../scripts/audit_dual.py) together.
BTH code at `0x00510000` and its loader view at `0x20510000` describe the same
physical allocation. A second memory node must not make either alias available
for a heap or another owner. Bootstrap, handoff/diagnostic slots and boot mailboxes
are reserved even when not every slot appears as a separate DTS node.

The effective M55 application DTCM must stop before the message region defined in
the resource contract. Loader, heartbeat, trace, doorbell, lifecycle, unallocated
tail and mailbox regions keep their declared owners. The lifecycle record assigns
the first 64 bytes to BTH and the last 64 bytes to M55. BTH may initialize shared
protocol state only after all relevant users are quiescent.

M55 TCM also has physical RAM-bank mappings. The recovery REPARK operation
temporarily uses three physical words named in the resource contract, with the
peer held in reset and selectors restored afterwards. These words and their
banks are not additional free memory. Static DTS checks supplement the ELF and
physical-bank audit; they do not replace it.

### Adding a resource user

For a new GPIO/UART instance, first identify the owner, clock/reset dependencies,
pad group, voltage, local IRQ route and interactions with M55 recovery. Unknown
board mappings remain unknown. A similar reference board is not sufficient
evidence for a connector assignment or electrical level.

Clock-rate queries, gate changes and shared-root reconfiguration are distinct
operations. Runtime services need defined calling context, bounded failure and
concurrency rules; an empty implementation must not report hardware support.
The current bootstrap HAL ABI is for BTH and is not directly callable from M55.
UART handoff must drain TX, transfer IRQ/state ownership and establish one runtime
writer while preserving early and fatal diagnostics. General GPIO/pinctrl,
power-domain control and system PM still require separate implementations and
hardware validation.
