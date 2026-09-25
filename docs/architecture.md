# Architecture and Code Ownership

[简体中文](architecture.zh-CN.md)

BTH (STAR-MC1) and M55 (Cortex-M55) run independent Zephyr kernels built from the same pinned Zephyr source revision. Message data lives in shared memory; mailbox interrupts notify the peer. See [hardware and board targets](hardware/bes2700yp.md#boards-and-build-targets).

## System components

Bootstrap initializes hardware on BTH, loads and starts BTH Zephyr, and retains hardware service entry points. BTH verifies, loads, and starts M55 Zephyr. The cores cooperate through public interfaces and a shared-memory protocol without depending on each other's private application directories.

## Build flow

One sysbuild invocation produces the complete image:

```text
M55 ELF
  → m55.segment.bin and m55_payload.h
  → BTH ELF (with embedded M55 image)
  → bth.payload.bin
  → bootstrap + HAL libraries → adapter.elf
  → image packaging and offline audit → zephyr.bin
```

`m55.segment.bin` records destination addresses, data locations, and lengths; `m55_payload.h` embeds it in BTH with validation metadata. `bth.payload.bin` carries the entry point and checks needed by bootstrap. The final `zephyr.bin` is the complete flash image.

[sysbuild/dual.cmake](../sysbuild/dual.cmake) orders the build; [M55 packaging](../scripts/pack_m55_payload.py), [BTH packaging](../scripts/pack_bth_payload.py), and [firmware packaging](../scripts/firmware.py) handle image creation and audit. See [build instructions](getting-started.md#build).

## Boot sequence

The default validation application runs for a bounded period, after which BTH stops M55; see [validation profiles](testing.md#validation-profiles).

1. Bootstrap initializes BTH hardware, checks the BTH payload, copies it to its runtime memory, and verifies the copy.
2. Bootstrap installs hardware service entry points, prepares interrupts and processor state, then transfers control to BTH Zephyr.
3. BTH verifies the service interface and embedded M55 image, prepares M55 clocks and memory through the service, and parks M55 in a wait program.
4. BTH copies M55 image segments to their destinations, verifies the copy, then starts M55 through the service.
5. M55 enters its Zephyr kernel and application. BTH checks peer status; the cores exchange shared-memory messages and use mailbox interrupts for notification.

See [bootstrap/adapter.c](../platforms/bes2700yp/boot/bootstrap/adapter.c), the [BTH application](../apps/bes2700yp/bth/src/main.c), and [runtime memory layout](hardware/bes2700yp.md#runtime-memory-layout).

## HAL and hardware-service boundary

Only bootstrap links the HAL libraries. BTH and M55 Zephyr images do not link them directly. After handoff, BTH calls retained services for M55 clock, memory, and startup control; the service code still executes on BTH. See [dual_service.c](../platforms/bes2700yp/boot/bootstrap/dual_service.c). `adapter` names bootstrap source and output, not another kernel.

## Directory responsibilities

| Directory | Responsibility |
|---|---|
| [apps/bes2700yp/bth](../apps/bes2700yp/bth) | BTH application and build configuration |
| [apps/bes2700yp/m55](../apps/bes2700yp/m55) | M55 application and build configuration |
| [bsp/](../bsp) | Board, SoC, DTS, and drivers |
| [platforms/bes2700yp/boot/bootstrap](../platforms/bes2700yp/boot/bootstrap) | BTH boot handoff, services, and diagnostics |
| [platforms/bes2700yp/ipc](../platforms/bes2700yp/ipc), [include/bestechnic/bes2700yp](../include/bestechnic/bes2700yp) | IPC, public interfaces, and shared-memory layout |
| [sysbuild/](../sysbuild), [scripts/](../scripts) | Multi-image build, packaging, audit, log analysis, and source archives |
| [tests/](../tests) | Host regressions and build checks |

The [Zephyr module declaration](../zephyr/module.yml) registers board, SoC, and DTS locations. Root [Kconfig](../Kconfig) and [CMakeLists.txt](../CMakeLists.txt) integrate drivers. This repository does not modify Zephyr kernel or architecture code.

## Build identity and provenance

The `build` list in [scripts/project_files.json](../scripts/project_files.json) selects source and configuration files for firmware identity. Their hashes, build parameters, toolchain version, module commits, and HAL manifest hash form the build-input digest. Documentation, tests, and editor files are outside that list but can enter source archives.

Git commits and source archives record provenance. Derived identifiers check build and core pairing; the complete-image SHA256 identifies final bytes. `validation_profile` selects test behavior, while `profile_id` matches boot diagnostics. Paths below are relative to a build directory such as `build/bes2700yp/main/`:

| Item | Purpose and location |
|---|---|
| Commits and worktree state | Integration and HAL provenance in `release/source-provenance.json`, summarized in `release/manifest.json` |
| `validation_profile` | Test behavior in identity, layout, and manifest |
| `source_sha256` | Build-input digest in `generated/identity.json` and `release/manifest.json` |
| BTH `build` | Payload and `release/layout.json` identifier derived from load contract, image, and inputs |
| `m55_build` | M55 status identifier derived from inputs, in identity and layout |
| `pair` | Core-pair identifier from inputs, in both core configurations and `layout.json` as `message_pair` |
| `profile` | Boot diagnostic identifier, in `layout.json` as `profile_id` |
| Image SHA256 | `firmware_sha256` in `release/manifest.json` and `release/SHA256SUMS` |

Uncommitted edits cannot be identified by commit alone. The package records source archives and file hashes; see [formal candidate provenance](../CONTRIBUTING.md#candidate-package-provenance).

## Offline audit

When producing the full image, [firmware.py](../scripts/firmware.py) invokes [layout checks](../scripts/check_bth_layout.py) and the [dual-core audit](../scripts/audit_dual.py). The audit checks:

- M55 image and BTH payload match their build outputs and satisfy load entry/checksum requirements.
- Loaded sections stay within each core's assigned memory and avoid shared, boot-service, and diagnostic regions.
- Mailbox interrupt routing, DTS, IPC parameters, and `pair` agree.
- Flash-initialization code and state occupy early RAM; critical functions are placed as expected.
- `bth_crc32` and `bth_copy_bytes` machine-code hashes match [t2-machine-code.json](../platforms/bes2700yp/boot/t2-machine-code.json), and startup-path call counts match expectations.

Results go to `release/offline-validation.json`. Layout or critical startup changes require corresponding interface, audit, and regression updates. Offline checks cannot replace [hardware boot and IPC testing](testing.md#hardware-validation).
