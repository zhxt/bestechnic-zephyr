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
int bes2700yp_uart0_read(struct bes2700yp_uart0_state *s)
{
 assert(mask==1);reads++;
 *s=(struct bes2700yp_uart0_state){.valid=7,.source=1,.source_hz=24000000,.configured_hz=24000000,.divider=1,
 .clocks=3,.reset_released=3,.rx_pin=18,.tx_pin=19,.rx_mux=4,.tx_mux=4,.pull_up=1};
 return bad_clock ? -2 : 0;
}
#include "../../platforms/bes2700yp/boot/bootstrap/arbitration.c"
#include "../../platforms/bes2700yp/boot/bootstrap/uart_resource_service.c"
static struct bes_uart_resource_io *io=(void *)BES_RESOURCE_RAM_START;
static struct bes_uart_resource_io original;
static void reset(void)
{
 memset(io,0xa5,sizeof(*io));
 io->abi=2;io->bytes=sizeof(*io);io->resource=2;io->flags=0;
 memset(io->reserved,0,sizeof(io->reserved));original=*io;reads=0;
}
static void rejected(uint32_t op,uint32_t addr,uint32_t size,int rc)
{
 struct bes_uart_resource_io before=*io;
 assert(bes_uart_resource_dispatch(op,addr,size)==rc);
 assert(!memcmp(io,&before,sizeof(*io)) && !reads);
}
int main(void)
{
 assert(mmap(io,BES_RESOURCE_RAM_END-BES_RESOURCE_RAM_START,PROT_READ|PROT_WRITE,
   MAP_PRIVATE|MAP_ANONYMOUS|MAP_FIXED_NOREPLACE,-1,0)==io);
 for(unsigned p=0;p<=5;p++) for(unsigned m=0;m<=1;m++) {
  reset();phase=p;mask=m;
  assert(!bes_uart_resource_dispatch(1,(uint32_t)(uintptr_t)io,sizeof(*io)));
  assert(mask==m && io->snapshot.phase==p && io->snapshot.valid==7);
  assert(reads==1 && !memcmp(io,&original,32));
  assert(io->snapshot.configured_hz==24000000);
  assert(io->snapshot.rx_pin==18 && io->snapshot.tx_pin==19);
 }
 reset();phase=3;bad_clock=1;
 assert(bes_uart_resource_dispatch(1,(uint32_t)(uintptr_t)io,sizeof(*io))==BES_UART_RESOURCE_BUSY);
 assert(!memcmp(io,&original,sizeof(*io)) && mask==1);bad_clock=0;
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
 io->abi=1;rejected(1,BES_RESOURCE_RAM_START,96,BES_RESOURCE_UNSUPPORTED);reset();
 io->resource=1;rejected(1,BES_RESOURCE_RAM_START,96,BES_RESOURCE_UNSUPPORTED);reset();
 io->flags=1;rejected(1,BES_RESOURCE_RAM_START,96,BES_RESOURCE_INVALID);reset();
 io->bytes=92;rejected(1,BES_RESOURCE_RAM_START,96,BES_RESOURCE_INVALID);reset();
 for(unsigned i=0;i<4;i++) { io->reserved[i]=1;rejected(1,BES_RESOURCE_RAM_START,96,BES_RESOURCE_INVALID);reset(); }
 io=(void *)(BES_RESOURCE_RAM_END-96);reset();
 assert(!bes_uart_resource_dispatch(1,(uint32_t)(uintptr_t)io,96));
 return 0;
}
