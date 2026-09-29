# SPDX-License-Identifier: Apache-2.0
cmake_minimum_required(VERSION 3.20)
set(CMAKE_SYSTEM_NAME Generic)
set(CMAKE_TRY_COMPILE_TARGET_TYPE STATIC_LIBRARY)
set(CMAKE_C_COMPILER ${CROSS_COMPILE}gcc)
set(CMAKE_ASM_COMPILER ${CROSS_COMPILE}gcc)
project(bes2700yp_bootstrap C ASM)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)
get_filename_component(bes_toolchain_bin "${CMAKE_C_COMPILER}" DIRECTORY)
get_filename_component(bes_toolchain_root "${bes_toolchain_bin}" DIRECTORY)
include(${HAL_ROOT}/cmake/import.cmake)
bes2700yp_import_hal(${HAL_ROOT} ${INTEGRATION_ROOT}/hal-release.sha256)
if(BES_M55_RESTART)
  add_compile_definitions(BES_BTH_M55_RESTART=1)
endif()
if(BES_ARBITRATION_PROBE)
  add_compile_definitions(BES_ARBITRATION_PROBE=1)
endif()
set(abi -mthumb -mcpu=cortex-m33 -mfpu=fpv5-sp-d16 -mfloat-abi=hard)
add_executable(adapter adapter.c handoff.S payload.S dual_service.c boot_profile.c copy_bytes.S
  resource_service.c uart_resource_service.c arbitration.c
  ${INTEGRATION_ROOT}/platforms/bes2700yp/resources/arbitration_contract.c
  ${INTEGRATION_ROOT}/platforms/bes2700yp/resources/uart_contract.c
  ${INTEGRATION_ROOT}/platforms/bes2700yp/resources/contract.c
  ${GENERATED_DIR}/build_info.c)
set_source_files_properties(dual_service.c resource_service.c uart_resource_service.c arbitration.c
  ${INTEGRATION_ROOT}/platforms/bes2700yp/resources/arbitration_contract.c
  ${INTEGRATION_ROOT}/platforms/bes2700yp/resources/uart_contract.c
  ${INTEGRATION_ROOT}/platforms/bes2700yp/resources/contract.c
  PROPERTIES COMPILE_OPTIONS "-fstack-usage;-mgeneral-regs-only")
if(BES_M55_RESTART)
  target_sources(adapter PRIVATE reset_timer.c)
endif()
set_target_properties(adapter PROPERTIES SUFFIX .elf)
target_include_directories(adapter PRIVATE . ${GENERATED_DIR} ${HAL_ROOT}/include
  ${CMSIS_ROOT}/CMSIS/Core/Include ${INTEGRATION_ROOT}/include/bestechnic/bes2700yp)
target_compile_options(adapter PRIVATE ${abi} -O2 -g -ffreestanding -fno-common
  -ffunction-sections -fdata-sections -fomit-frame-pointer -fsigned-char
  -fno-aggressive-loop-optimizations -fno-isolate-erroneous-paths-dereference
  -fno-tree-loop-distribute-patterns -fno-tree-switch-conversion -fno-strict-aliasing
  -Wall -Wextra -Werror -Werror=date-time
  -ffile-prefix-map=${INTEGRATION_ROOT}=bestechnic-zephyr
  -ffile-prefix-map=${GENERATED_DIR}=generated
  -ffile-prefix-map=${CMAKE_BINARY_DIR}=bootstrap
  -ffile-prefix-map=${CMSIS_ROOT}=cmsis_6
  -ffile-prefix-map=${HAL_ROOT}=hal_bestechnic
  # Compiler headers enter DWARF, which contributes to the ELF build ID.
  -ffile-prefix-map=${bes_toolchain_root}=toolchain
  $<$<COMPILE_LANGUAGE:ASM>:-Wa,--debug-prefix-map=${INTEGRATION_ROOT}=bestechnic-zephyr>
  $<$<COMPILE_LANGUAGE:ASM>:-Wa,--debug-prefix-map=${CMAKE_BINARY_DIR}=bootstrap>)
target_compile_definitions(adapter PRIVATE BES_BTH_DUAL_BOOT BES_BTH_LOG_PREFIX
  BES_BTH_BOOT_PROFILE BES_BTH_BOOT_CRC_RAM BES_BTH_BOOT_COPY_RAM
  BTH_PAYLOAD_FILE="${GENERATED_DIR}/bth.payload.bin")
set_property(SOURCE payload.S APPEND PROPERTY OBJECT_DEPENDS ${GENERATED_DIR}/bth.payload.bin)
set(linker ${HAL_ROOT}/linker/bes2700yp/dual_v1.ld)
target_link_options(adapter PRIVATE ${abi} -static -nostdlib -T${linker}
  -Wl,-X,--no-wchar-size-warning,--print-memory-usage,--build-id,--gc-sections,-Map=adapter.map)
set_property(TARGET adapter APPEND PROPERTY LINK_DEPENDS ${linker})
target_link_libraries(adapter PRIVATE -Wl,--whole-archive
  bes2700yp_bootstrap_compat bes2700yp_system bes2700yp_flash -Wl,--no-whole-archive)
