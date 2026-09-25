# SPDX-License-Identifier: Apache-2.0

zephyr_include_directories(.)

if(CONFIG_SOC_BES2700YP_CM55)
  zephyr_sources(soc_bes2700yp_cm55.c)
  zephyr_sources_ifdef(CONFIG_ARM_MPU mpu_regions.c)
  zephyr_linker_sources(SECTIONS linker/bes2700_cm55_shared.ld)
elseif(CONFIG_SOC_BES2700YP_BTH)
  zephyr_sources(soc_bes2700yp_bth.c bth_reset.S)
endif()

set(SOC_LINKER_SCRIPT ${ZEPHYR_BASE}/include/zephyr/arch/arm/cortex_m/scripts/linker.ld CACHE INTERNAL "")
