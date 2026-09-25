# SPDX-License-Identifier: Apache-2.0
get_filename_component(BES_ROOT ${APP_DIR}/../../.. ABSOLUTE)
if(DEFINED BES_PACKAGE)
  message(FATAL_ERROR "BES_PACKAGE was replaced by BES_VALIDATION_PROFILE; use a fresh build directory")
endif()
set(BES_VALIDATION_PROFILE "ipc-backpressure" CACHE STRING "Validation scenario for this application")
include(${BES_ROOT}/sysbuild/dual.cmake)
