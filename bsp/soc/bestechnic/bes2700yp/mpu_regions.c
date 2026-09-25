/*
 * SPDX-License-Identifier: Apache-2.0
 */

#include <zephyr/devicetree.h>
#include <zephyr/arch/arm/mpu/arm_mpu_mem_cfg.h>

static const struct arm_mpu_region mpu_regions[] = {
	MPU_REGION_ENTRY("ITCM",
			 DT_REG_ADDR(DT_NODELABEL(m55_itcm)),
			 REGION_RAM_ATTR_WITH_EXEC(DT_REG_ADDR(DT_NODELABEL(m55_itcm)),
						   DT_REG_SIZE(DT_NODELABEL(m55_itcm)))),

	MPU_REGION_ENTRY("DTCM",
			 DT_REG_ADDR(DT_NODELABEL(m55_dtcm)),
			 REGION_RAM_ATTR(DT_REG_ADDR(DT_NODELABEL(m55_dtcm)),
					 DT_REG_SIZE(DT_NODELABEL(m55_dtcm)))),
#if DT_NODE_EXISTS(DT_NODELABEL(m55_ipc))
	MPU_REGION_ENTRY("IPC", DT_REG_ADDR(DT_NODELABEL(m55_ipc)),
		REGION_RAM_NOCACHE_ATTR(DT_REG_ADDR(DT_NODELABEL(m55_ipc)),
			DT_REG_SIZE(DT_NODELABEL(m55_ipc)))),
	MPU_REGION_ENTRY("IPC_DIAG", DT_REG_ADDR(DT_NODELABEL(m55_ipc_diag)),
		REGION_RAM_NOCACHE_ATTR(DT_REG_ADDR(DT_NODELABEL(m55_ipc_diag)),
			DT_REG_SIZE(DT_NODELABEL(m55_ipc_diag)))),
#endif
};

const struct arm_mpu_config mpu_config = {
	.num_regions = ARRAY_SIZE(mpu_regions),
	.mpu_regions = mpu_regions,
};
