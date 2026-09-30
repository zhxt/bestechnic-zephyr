# SPDX-License-Identifier: Apache-2.0
zephyr_library()
zephyr_library_sources(gpio_bes2700yp.c)
zephyr_library_sources(
  ${CMAKE_CURRENT_LIST_DIR}/../../../platforms/bes2700yp/boot/service_contract.c
  ${CMAKE_CURRENT_LIST_DIR}/../../../platforms/bes2700yp/resources/contract.c
  ${CMAKE_CURRENT_LIST_DIR}/../../../platforms/bes2700yp/resources/gpio_client.c
  ${CMAKE_CURRENT_LIST_DIR}/../../../platforms/bes2700yp/resources/gpio_contract.c
)
