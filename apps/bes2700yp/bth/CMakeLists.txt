# SPDX-License-Identifier: Apache-2.0
cmake_minimum_required(VERSION 3.20.0)
find_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})
project(bes2700_bth_dual_message)
if(NOT CONFIG_GPIO_BES2700YP)
  target_sources(app PRIVATE
    ${CMAKE_CURRENT_LIST_DIR}/../../../platforms/bes2700yp/boot/service_contract.c
    ${CMAKE_CURRENT_LIST_DIR}/../../../platforms/bes2700yp/resources/contract.c)
endif()
target_sources(app PRIVATE
  ${CMAKE_CURRENT_LIST_DIR}/../../../platforms/bes2700yp/resources/client.c
  ${CMAKE_CURRENT_LIST_DIR}/../../../platforms/bes2700yp/resources/uart_contract.c
  ${CMAKE_CURRENT_LIST_DIR}/../../../platforms/bes2700yp/resources/uart_client.c
  ${CMAKE_CURRENT_LIST_DIR}/../../../platforms/bes2700yp/resources/arbitration_contract.c
  ${CMAKE_CURRENT_LIST_DIR}/../../../platforms/bes2700yp/resources/arbitration_client.c
  ${CMAKE_CURRENT_LIST_DIR}/../../../platforms/bes2700yp/resources/probe.c)
zephyr_get(DUAL_GENERATED_DIR SYSBUILD)
if(CONFIG_BES2700_M55_RESTART)
  target_sources(app PRIVATE src/restart.c
    ${CMAKE_CURRENT_LIST_DIR}/../../../platforms/bes2700yp/lifecycle/manager.c
    ${CMAKE_CURRENT_LIST_DIR}/../../../platforms/bes2700yp/lifecycle/health.c)
else()
  target_sources(app PRIVATE src/main.c)
endif()
if(NOT DUAL_GENERATED_DIR)
  message(FATAL_ERROR "DUAL_GENERATED_DIR is required; use west build --sysbuild")
endif()
target_include_directories(app PRIVATE ${DUAL_GENERATED_DIR})

target_sources(app PRIVATE ${CMAKE_CURRENT_LIST_DIR}/../../../platforms/bes2700yp/ipc/worker.c)
target_compile_definitions(app PRIVATE CC_BTH=1)
target_include_directories(app PRIVATE ${CMAKE_CURRENT_LIST_DIR}/../../../platforms/bes2700yp/ipc)

get_filename_component(bes_workspace ${CMAKE_CURRENT_LIST_DIR}/../../../.. ABSOLUTE)
get_filename_component(bes_build ${PROJECT_BINARY_DIR}/.. ABSOLUTE)
zephyr_compile_options(-ffile-prefix-map=${bes_workspace}=workspace
  -ffile-prefix-map=${bes_build}=build
  $<$<COMPILE_LANGUAGE:ASM>:-Wa,--debug-prefix-map=${bes_workspace}=workspace>
  $<$<COMPILE_LANGUAGE:ASM>:-Wa,--debug-prefix-map=${bes_build}=build>)

if(CONFIG_BES2700YP_GPIO_VALIDATION GREATER 0)
  if(CONFIG_GPIO_BES2700YP_IRQ)
    target_sources(app PRIVATE src/gpio_irq_validation.c)
  elseif(CONFIG_BES2700_M55_RESTART)
    target_sources(app PRIVATE src/gpio_restart.c)
  else()
    target_sources(app PRIVATE src/gpio_validation.c)
  endif()
  if(NOT CONFIG_GPIO_BES2700YP)
    target_sources(app PRIVATE
      ${CMAKE_CURRENT_LIST_DIR}/../../../platforms/bes2700yp/resources/gpio_client.c
      ${CMAKE_CURRENT_LIST_DIR}/../../../platforms/bes2700yp/resources/gpio_contract.c)
  endif()
endif()
