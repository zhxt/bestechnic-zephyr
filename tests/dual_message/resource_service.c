/* SPDX-License-Identifier: Apache-2.0 */
#define _GNU_SOURCE
#include <assert.h>
#include <stdint.h>
#include <string.h>
#include <sys/mman.h>
#define BES2700YP_BOOTSTRAP_ARCH_H
#define BES_RESOURCE_HOST_TEST
static uint32_t ipsr, control, mask, phase;
static unsigned reads;
static int bad_clock;
static uint32_t __get_IPSR(void) { return ipsr; }
static uint32_t __get_CONTROL(void) { return control; }
static uint32_t __get_PRIMASK(void) { return mask; }
static void __disable_irq(void) { mask=1; }
static void __set_PRIMASK(uint32_t v) { mask=v; }
#include <bestechnic/bes2700yp/hw.h>
uint32_t dual_service_phase(void) { return phase; }
int bes2700yp_clocks_are_24m(void) { assert(mask==1); reads++; return bad_clock; }
void bes2700yp_snapshot(struct bes2700yp_hw_snapshot *s)
{
 assert(phase>=2 && mask==1); reads++;
 *s=(struct bes2700yp_hw_snapshot){.core_vtor=0x200c0000,.ram_sel0=0x12345678};
}
#include "../../platforms/bes2700yp/boot/bootstrap/arbitration.c"
#include "../../platforms/bes2700yp/boot/bootstrap/resource_service.c"
static struct bes_resource_io *io=(void *)BES_RESOURCE_RAM_START;
static struct bes_resource_io original;
static void reset(void)
{
 memset(io,0xa5,sizeof(*io));
 io->abi=1;io->bytes=sizeof(*io);io->resource=1;io->flags=0;
 memset(io->reserved,0,sizeof(io->reserved));original=*io;reads=0;
}
static void rejected(uint32_t op,uint32_t addr,uint32_t size,int rc)
{
 struct bes_resource_io before=*io;
 assert(bes_resource_dispatch(op,addr,size)==rc);
 assert(!memcmp(io,&before,sizeof(*io)) && !reads);
}
int main(void)
{
 assert(mmap(io,BES_RESOURCE_RAM_END-BES_RESOURCE_RAM_START,PROT_READ|PROT_WRITE,
   MAP_PRIVATE|MAP_ANONYMOUS|MAP_FIXED_NOREPLACE,-1,0)==io);
 for(unsigned p=0;p<=5;p++) for(unsigned m=0;m<=1;m++) {
  reset();phase=p;mask=m;
  assert(!bes_resource_dispatch(1,(uint32_t)(uintptr_t)io,sizeof(*io)));
  assert(mask==m && io->snapshot.phase==p && io->snapshot.valid==(p<2?1:7));
  assert(reads==(p<2?0:2) && !memcmp(io,&original,32));
  assert(io->snapshot.clocks_24m==(p>=2));
  assert(!io->snapshot.reserved[0] && !io->snapshot.reserved[1] && !io->snapshot.reserved[2]);
 }
 reset();phase=3;bad_clock=1;
 assert(!bes_resource_dispatch(1,(uint32_t)(uintptr_t)io,sizeof(*io)));
 assert(io->snapshot.valid==7 && !io->snapshot.clocks_24m);bad_clock=0;
 for(unsigned m=0;m<2;m++) {
  reset();mask=m;bes_arbitration_state.owner=3;
  rejected(1,BES_RESOURCE_RAM_START,96,BES_RESOURCE_BUSY);
  assert(mask==m);bes_arbitration_state.owner=0;
 }
 reset();ipsr=1;rejected(1,BES_RESOURCE_RAM_START,96,BES_RESOURCE_CONTEXT);ipsr=0;
 control=1;rejected(1,BES_RESOURCE_RAM_START,96,BES_RESOURCE_CONTEXT);control=0;
 rejected(0,BES_RESOURCE_RAM_START,96,BES_RESOURCE_UNSUPPORTED);
 uint32_t invalid[]={0,0xffffffff,0xffffffc0,0x2015c000,0x2053fffc,0x00540000,
   BES_RESOURCE_RAM_START+1,BES_RESOURCE_RAM_END-92,BES_RESOURCE_RAM_END};
 for(unsigned i=0;i<sizeof(invalid)/4;i++) rejected(1,invalid[i],96,BES_RESOURCE_INVALID);
 rejected(1,BES_RESOURCE_RAM_START,0,BES_RESOURCE_INVALID);
 rejected(1,BES_RESOURCE_RAM_START,0xffffffff,BES_RESOURCE_INVALID);
 io->abi=2;rejected(1,BES_RESOURCE_RAM_START,96,BES_RESOURCE_UNSUPPORTED);reset();
 io->resource=2;rejected(1,BES_RESOURCE_RAM_START,96,BES_RESOURCE_UNSUPPORTED);reset();
 io->flags=1;rejected(1,BES_RESOURCE_RAM_START,96,BES_RESOURCE_INVALID);reset();
 io->bytes=92;rejected(1,BES_RESOURCE_RAM_START,96,BES_RESOURCE_INVALID);reset();
 for(unsigned i=0;i<4;i++) { io->reserved[i]=1;rejected(1,BES_RESOURCE_RAM_START,96,BES_RESOURCE_INVALID);reset(); }
 io=(void *)(BES_RESOURCE_RAM_END-96);reset();
 assert(!bes_resource_dispatch(1,(uint32_t)(uintptr_t)io,96));
 return 0;
}
