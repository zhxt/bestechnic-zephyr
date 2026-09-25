# SPDX-License-Identifier: Apache-2.0
cmake_minimum_required(VERSION 3.20)
get_filename_component(BES_ROOT ${CMAKE_CURRENT_LIST_DIR}/../../../.. ABSOLUTE)
get_filename_component(BES_WORKSPACE ${BES_ROOT}/.. ABSOLUTE)
set(ZEPHYR_BASE ${BES_WORKSPACE}/zephyr CACHE PATH "Pinned Zephyr tree")
set(BOARD_ROOT ${BES_ROOT}/bsp CACHE STRING "BES2700YP external BSP")
set(SOC_ROOT ${BES_ROOT}/bsp CACHE STRING "BES2700YP external SoC")
set(DTS_ROOT ${BES_ROOT}/bsp CACHE STRING "BES2700YP external DTS")
set(ZEPHYR_MODULES
  "${BES_ROOT};${BES_WORKSPACE}/modules/hal/bestechnic;${BES_WORKSPACE}/modules/hal/cmsis;${BES_WORKSPACE}/modules/hal/cmsis_6"
  CACHE STRING "Declared firmware dependencies")
find_package(Sysbuild REQUIRED HINTS ${ZEPHYR_BASE}/share/sysbuild/cmake)
project(sysbuild LANGUAGES)
