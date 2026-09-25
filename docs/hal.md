# Bestechnic HAL Module

[简体中文](hal.zh-CN.md)

`hal_bestechnic` supplies prebuilt HAL libraries, a public interface header, and a linker script for the BES2700YP Zephyr integration. Bootstrap links the libraries for early hardware initialization and retains service entry points for BTH. The BTH and M55 Zephyr images do not link the HAL libraries directly; see [architecture](architecture.md#hal-and-hardware-service-boundary).

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
