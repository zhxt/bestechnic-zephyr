/* SPDX-License-Identifier: Apache-2.0 */
#include <bes2700_dual_boot.h>

uint32_t dual_service_validate(const volatile struct dual_service *service)
{
	uint32_t entry = service->dispatch;
	uint32_t code = entry & ~1U;
	uint32_t errors = 0;

	if (service->magic != DUAL_SERVICE_MAGIC) {
		errors |= DUAL_SERVICE_BAD_MAGIC;
	}
	if (service->layout != DUAL_LAYOUT) {
		errors |= DUAL_SERVICE_BAD_LAYOUT;
	}
	if (!(entry & 1U)) {
		errors |= DUAL_SERVICE_BAD_THUMB;
	}
	if (!((code >= DUAL_SERVICE_FLASHX_START && code < DUAL_SERVICE_FLASHX_END) ||
	      (code >= DUAL_SERVICE_SRAM_START && code < DUAL_SERVICE_SRAM_END))) {
		errors |= DUAL_SERVICE_BAD_EXEC;
	}
	if (service->itcm != DUAL_ITCM || service->itcm_size != 0x40000U) {
		errors |= DUAL_SERVICE_BAD_ITCM;
	}
	if (service->dtcm != DUAL_DTCM || service->dtcm_size != 0xa0000U) {
		errors |= DUAL_SERVICE_BAD_DTCM;
	}
	if (service->mailbox != DUAL_MAILBOX) {
		errors |= DUAL_SERVICE_BAD_MAILBOX;
	}
	return errors;
}
