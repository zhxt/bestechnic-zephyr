# SPDX-License-Identifier: Apache-2.0
get_filename_component(BES_WORKSPACE ${BES_ROOT}/.. ABSOLUTE)
set(BES_HAL ${BES_WORKSPACE}/modules/hal/bestechnic)
set(BES_GENERATED ${CMAKE_BINARY_DIR}/generated)
option(BES_FORMAL_PACKAGE "Require fixed clean commits for source packaging" OFF)
set(bes_package_args)
if(BES_FORMAL_PACKAGE)
  list(APPEND bes_package_args --formal)
endif()
if(NOT "${BOARD}/${BOARD_QUALIFIERS}" STREQUAL "bes2700yp_devkit/bes2700yp/bth")
  message(FATAL_ERROR "This integration supports only bes2700yp_devkit/bes2700yp/bth")
endif()
if(NOT CROSS_COMPILE)
  set(CROSS_COMPILE "$ENV{CROSS_COMPILE}" CACHE STRING "GNU Arm compiler prefix")
endif()
if(NOT CROSS_COMPILE OR NOT ZEPHYR_TOOLCHAIN_VARIANT STREQUAL "cross-compile")
  message(FATAL_ERROR "Select cross-compile and the pinned GNU Arm 10.3 compiler prefix")
endif()
file(GLOB_RECURSE bes_inputs CONFIGURE_DEPENDS
  ${BES_ROOT}/apps/* ${BES_ROOT}/bsp/* ${BES_ROOT}/include/*
  ${BES_ROOT}/platforms/* ${BES_ROOT}/scripts/*.py ${BES_ROOT}/scripts/project_files.json ${BES_ROOT}/sysbuild/*)
set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS ${bes_inputs}
  ${BES_ROOT}/hal-release.sha256 ${BES_ROOT}/module-lock.json ${BES_HAL}/manifest.json
  ${BES_ROOT}/scripts/validation_profiles.py)
execute_process(COMMAND ${Python3_EXECUTABLE} ${BES_ROOT}/scripts/firmware.py configure
  --generated ${BES_GENERATED} --hal ${BES_HAL} --cross ${CROSS_COMPILE} --profile "${BES_VALIDATION_PROFILE}" ${bes_package_args}
  COMMAND_ERROR_IS_FATAL ANY)
include(${BES_GENERATED}/validation.cmake)
set_property(CACHE BES_VALIDATION_PROFILE PROPERTY STRINGS ${BES_VALIDATION_PROFILES})
set(bth_DUAL_GENERATED_DIR ${BES_GENERATED} CACHE PATH "Generated M55 payload" FORCE)
set(bth_EXTRA_CONF_FILE ${BES_GENERATED}/bth.conf CACHE STRING "BTH common profile" FORCE)
set(m55_EXTRA_CONF_FILE ${BES_GENERATED}/m55.conf CACHE STRING "M55 common profile" FORCE)
ExternalZephyrProject_Add(APPLICATION m55 SOURCE_DIR ${BES_ROOT}/apps/bes2700yp/m55
  BOARD bes2700yp_devkit/bes2700yp/cm55)
add_custom_target(m55_payload
  COMMAND ${Python3_EXECUTABLE} ${BES_ROOT}/scripts/firmware.py m55
    --generated ${BES_GENERATED} --elf ${CMAKE_BINARY_DIR}/m55/zephyr/zephyr.elf --cross ${CROSS_COMPILE}
  BYPRODUCTS ${BES_GENERATED}/m55_payload.h ${BES_GENERATED}/m55.segment.bin
    ${BES_GENERATED}/m55-layout.json
  DEPENDS m55 USES_TERMINAL VERBATIM)
add_dependencies(bth m55_payload)
add_custom_target(bth_payload
  COMMAND ${Python3_EXECUTABLE} ${BES_ROOT}/scripts/firmware.py bth
    --generated ${BES_GENERATED} --elf ${CMAKE_BINARY_DIR}/bth/zephyr/zephyr.elf --cross ${CROSS_COMPILE}
  BYPRODUCTS ${BES_GENERATED}/bth.payload.bin ${BES_GENERATED}/bth-layout.json
  DEPENDS bth USES_TERMINAL VERBATIM)
ExternalProject_Add(bootstrap
  SOURCE_DIR ${BES_ROOT}/platforms/bes2700yp/boot/bootstrap
  BINARY_DIR ${CMAKE_BINARY_DIR}/bootstrap
  CMAKE_ARGS -DCROSS_COMPILE=${CROSS_COMPILE} -DHAL_ROOT=${BES_HAL}
    -DBES_M55_RESTART=${BES_VALIDATION_M55_RESTART} -DINTEGRATION_ROOT=${BES_ROOT} -DGENERATED_DIR=${BES_GENERATED}
    -DCMSIS_ROOT=${BES_WORKSPACE}/modules/hal/cmsis_6
  BUILD_COMMAND ${CMAKE_COMMAND} --build .
  BUILD_BYPRODUCTS ${CMAKE_BINARY_DIR}/bootstrap/adapter.elf ${CMAKE_BINARY_DIR}/bootstrap/adapter.map
  BUILD_ALWAYS TRUE INSTALL_COMMAND "" DEPENDS bth_payload USES_TERMINAL_BUILD TRUE)
add_custom_target(firmware ALL
  COMMAND ${Python3_EXECUTABLE} ${BES_ROOT}/scripts/firmware.py final
    --generated ${BES_GENERATED} --elf ${CMAKE_BINARY_DIR}/bootstrap/adapter.elf
    --hal ${BES_HAL} --cross ${CROSS_COMPILE}
  BYPRODUCTS ${CMAKE_BINARY_DIR}/zephyr.bin ${CMAKE_BINARY_DIR}/layout.json
    ${CMAKE_BINARY_DIR}/offline-validation.json ${CMAKE_BINARY_DIR}/release/manifest.json
  DEPENDS bootstrap USES_TERMINAL VERBATIM)
add_custom_target(check
  COMMAND ${Python3_EXECUTABLE} ${BES_ROOT}/scripts/test_host.py
  DEPENDS firmware USES_TERMINAL VERBATIM)
add_custom_target(release DEPENDS check)
