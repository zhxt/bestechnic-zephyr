/* SPDX-License-Identifier: Apache-2.0 */
#define _GNU_SOURCE
#include <assert.h>
#include <stdint.h>
#include <string.h>
#include <sys/mman.h>
#define BES2700YP_BOOTSTRAP_ARCH_H
#define BES_RESOURCE_HOST_TEST
static uint32_t ipsr,control,mask,phase;
static uint32_t __get_IPSR(void) { return ipsr; }
static uint32_t __get_CONTROL(void) { return control; }
static uint32_t __get_PRIMASK(void) { return mask; }
static void __disable_irq(void) { mask=1; }
static void __set_PRIMASK(uint32_t v) { mask=v; }
uint32_t dual_service_phase(void) { return phase; }
#include "../../platforms/bes2700yp/boot/bootstrap/arbitration.c"
int main(void)
{
 struct bes_arbitration_io *io=(void *)BES_RESOURCE_RAM_START;
 assert(mmap(io,4096,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS|MAP_FIXED_NOREPLACE,-1,0)==io);
 for(unsigned p=0;p<6;p++) for(unsigned m=0;m<2;m++) {
  phase=p;mask=m;*io=(struct bes_arbitration_io){.abi=3,.bytes=96,.resource=3};
  assert(!bes_arbitration_dispatch(1,BES_RESOURCE_RAM_START,96));
  assert(mask==m && io->snapshot.phase==p && io->snapshot.abi==3 && io->snapshot.bytes==64);
 }
 struct bes_arbitration_io old=*io;
 ipsr=1;assert(bes_arbitration_dispatch(1,BES_RESOURCE_RAM_START,96)==-3);ipsr=0;
 control=1;assert(bes_arbitration_dispatch(1,BES_RESOURCE_RAM_START,96)==-3);control=0;
 assert(bes_arbitration_dispatch(2,BES_RESOURCE_RAM_START,96)==-2);
 assert(bes_arbitration_dispatch(1,BES_RESOURCE_RAM_START+1,96)==-1);
 assert(bes_arbitration_dispatch(1,BES_RESOURCE_RAM_START,92)==-1);
 assert(!memcmp(io,&old,96));
 for(unsigned n=0;n<8;n++) {
  *io=old;((uint32_t *)io)[n]^=1;
  struct bes_arbitration_io before=*io;
  assert(bes_arbitration_dispatch(1,BES_RESOURCE_RAM_START,96)==(n==0||n==2?-2:-1));
  assert(!memcmp(io,&before,96));
 }
 mask=1;assert(bes_arbitration_enter(DUAL_PARK,1)==BES_ARBITRATION_CONTEXT);assert(mask==1);
 mask=0;ipsr=1;assert(bes_arbitration_enter(DUAL_PARK,1)==BES_ARBITRATION_CONTEXT);ipsr=0;
 control=1;assert(bes_arbitration_enter(DUAL_PARK,1)==BES_ARBITRATION_CONTEXT);control=0;
 assert(!bes_arbitration_enter(DUAL_PARK,1) && mask==0);
 assert(bes_arbitration_enter(DUAL_STOP,1)==BES_ARBITRATION_BUSY && !bes_arbitration_state.pending);
 assert(bes_arbitration_enter(DUAL_RELEASE,2)==BES_ARBITRATION_BUSY);
 for(unsigned n=0;n<3;n++) assert(bes_arbitration_enter(DUAL_STOP,2)==BES_ARBITRATION_BUSY);
 assert(bes_arbitration_state.pending==1 && bes_arbitration_state.stop_requests==3 && mask==0);
 *io=old;assert(!bes_arbitration_dispatch(1,BES_RESOURCE_RAM_START,96));
 assert(io->snapshot.owner==DUAL_PARK && io->snapshot.pending==1 && io->snapshot.entered==1);
 assert(io->snapshot.busy==5 && io->snapshot.stop_requests==3 && !io->snapshot.exited);
 mask=1;bes_arbitration_leave(-7);assert(mask==1 && !bes_arbitration_busy());mask=0;
 assert(!bes_arbitration_enter(DUAL_STOP,3));
 mask=1;bes_arbitration_leave(0);mask=0;
 assert(bes_arbitration_state.entered==2 && bes_arbitration_state.exited==2);
 return 0;
}
