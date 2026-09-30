# SPDX-License-Identifier: Apache-2.0
zephyr_include_directories(include/bestechnic/bes2700yp platforms/bes2700yp/boot/bootstrap)
add_subdirectory_ifdef(CONFIG_MBOX_BES2700 bsp/drivers/mbox)
add_subdirectory_ifdef(CONFIG_UART_BES2700 bsp/drivers/serial)
add_subdirectory_ifdef(CONFIG_GPIO_BES2700YP bsp/drivers/gpio)
