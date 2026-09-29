/* SPDX-License-Identifier: Apache-2.0 */
#include "arch.h"
#include "arbitration.h"
#include <bes2700_dual_boot.h>
volatile struct bes_arbitration_snapshot bes_arbitration_state;
uint32_t dual_service_phase(void);

uint32_t bes_arbitration_busy(void) { return bes_arbitration_state.owner; }

int bes_arbitration_enter(uint32_t op, uint32_t phase)
{
 if (__get_IPSR() || (__get_CONTROL() & 1U) || __get_PRIMASK()) {
  return BES_ARBITRATION_CONTEXT;
 }
 uint32_t mask=__get_PRIMASK();
 __disable_irq();
 int rc=0;
 if (bes_arbitration_state.owner) {
  bes_arbitration_state.busy++;
  if (op==DUAL_STOP && phase>=2U) {
   bes_arbitration_state.pending=1;
   bes_arbitration_state.stop_requests++;
  }
  rc=BES_ARBITRATION_BUSY;
 } else {
  bes_arbitration_state.owner=op;
  bes_arbitration_state.entered++;
 }
 __set_PRIMASK(mask);
 return rc;
}

void bes_arbitration_leave(int rc)
{
 bes_arbitration_state.last_op=bes_arbitration_state.owner;
 bes_arbitration_state.last_rc=(uint32_t)rc;
 bes_arbitration_state.exited++;
 bes_arbitration_state.owner=0;
}

int32_t bes_arbitration_dispatch(uint32_t op, uint32_t address, uint32_t bytes)
{
 if (__get_IPSR() || (__get_CONTROL() & 1U)) { return BES_RESOURCE_CONTEXT; }
 if (op!=BES_RESOURCE_SNAPSHOT) { return BES_RESOURCE_UNSUPPORTED; }
 if (!bes_resource_buffer_valid(address,bytes)) { return BES_RESOURCE_INVALID; }
 struct bes_arbitration_io *io=(void *)(uintptr_t)address;
 if (io->abi!=BES_ARBITRATION_ABI || io->resource!=BES_ARBITRATION_ID) {
  return BES_RESOURCE_UNSUPPORTED;
 }
 if (io->bytes!=bytes || io->flags || io->reserved[0] || io->reserved[1] ||
     io->reserved[2] || io->reserved[3]) { return BES_RESOURCE_INVALID; }
 uint32_t mask=__get_PRIMASK();
 __disable_irq();
 volatile struct bes_arbitration_snapshot *out=&io->snapshot;
 out->abi=BES_ARBITRATION_ABI;out->bytes=sizeof(*out);
#define COPY(n) out->n=bes_arbitration_state.n;
 BES_ARBITRATION_FIELDS(COPY)
#undef COPY
 out->phase=dual_service_phase();
 __set_PRIMASK(mask);
 return BES_RESOURCE_OK;
}
#ifndef BES_RESOURCE_HOST_TEST
const struct bes_resource_descriptor bes_arbitration_service = {
 .magic=BES_RESOURCE_MAGIC, .abi=BES_ARBITRATION_ABI,
 .bytes=sizeof(struct bes_resource_descriptor), .capabilities=BES_ARBITRATION_CAP,
 .dispatch=(uint32_t)(uintptr_t)bes_arbitration_dispatch,
 .request_bytes=sizeof(struct bes_arbitration_io),
 .snapshot_bytes=sizeof(struct bes_arbitration_snapshot),
};
#endif
