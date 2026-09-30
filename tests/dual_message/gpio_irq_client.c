/* SPDX-License-Identifier: Apache-2.0 */
/* x86_64 host trampolines at valid Thumb addresses test the real client path. */
#define _GNU_SOURCE
#include <assert.h>
#include <errno.h>
#include <stdint.h>
#include <string.h>
#include <sys/mman.h>
#include <bes2700yp_gpio_irq.h>
#include <bes2700_dual_boot.h>
static uint32_t returned=0x34000000;
static unsigned calls;
static int response;
static int32_t discover(uint32_t op, uint32_t abi)
{ assert(op==9 && abi==5); calls++;return (int32_t)returned; }
static int32_t dispatch(uint32_t op, uint32_t address, uint32_t bytes)
{
 calls++;
 if(op==1){
  assert(bytes==96 && address==BES_RESOURCE_RAM_START);
  struct bes_gpio_irq_io *io=(void *)(uintptr_t)address;
  assert(io->abi==5 && io->bytes==96);
  for(unsigned i=0;i<6;i++){assert(!io->reserved[i]);}
  io->state.enabled=0x30000;
 }
 return response;
}
static void *map(uint32_t address)
{
 void *ptr=(void *)(uintptr_t)address;
 assert(mmap(ptr,4096,PROT_READ|PROT_WRITE|PROT_EXEC,
  MAP_PRIVATE|MAP_ANONYMOUS|MAP_FIXED_NOREPLACE,-1,0)==ptr);return ptr;
}
static void jump(uint32_t address, uintptr_t function)
{
 unsigned char *p=(void *)(uintptr_t)address;
 /* movabs rax, function; jmp rax */
 p[0]=0x48;p[1]=0xb8;memcpy(p+2,&function,8);p[10]=0xff;p[11]=0xe0;
}
int main(void)
{
 map(0x14000000);jump(0x14000001,(uintptr_t)discover);jump(0x14000021,(uintptr_t)dispatch);
 struct bes_resource_descriptor *d=map(0x34000000);
 map(0x2055c000);struct dual_service *root=(void *)DUAL_SERVICE_ADDR;
 *root=(struct dual_service){.magic=DUAL_SERVICE_MAGIC,.layout=DUAL_LAYOUT,.dispatch=0x14000001,
 .itcm=DUAL_ITCM,.itcm_size=0x40000,.dtcm=DUAL_DTCM,.dtcm_size=0xa0000,.mailbox=DUAL_MAILBOX};
 struct bes_gpio_irq_io *io=map(BES_RESOURCE_RAM_START);
 *d=(struct bes_resource_descriptor){BES_RESOURCE_MAGIC,5,32,64,0x14000021,96,64,0};
 assert(bes_gpio_irq_call(2,0,0)==-ENODEV && !calls);
 root->magic=0;assert(bes_gpio_irq_connect()==-ENODEV && !calls);root->magic=DUAL_SERVICE_MAGIC;
 uint32_t invalid[]={0,0xffffffff,0x20540000,0x34000001,0x347fffe4};
 for(unsigned i=0;i<sizeof(invalid)/4;i++){returned=invalid[i];assert(bes_gpio_irq_connect()==-ENOTSUP);}
 returned=0x34000000;
 for(unsigned i=1;i<8;i++){
  uint32_t *fields=(void *)d,old=fields[i];fields[i]=0;
  if(i==7){fields[i]=1;}
  assert(bes_gpio_irq_connect()==-ENOTSUP);fields[i]=old;
 }
 assert(!bes_gpio_irq_connect());unsigned before=calls;
 assert(bes_gpio_irq_read((void *)0x2055bfa4)==-EINVAL && calls==before);
 assert(!bes_gpio_irq_read(io) && io->state.enabled==0x30000);
 int statuses[]={-1,-2,-3,-4,-5,-6,-99,123,0x10000};
 int errors[]={-EINVAL,-EBUSY,-ENODEV,-EIO,-EACCES,-EWOULDBLOCK,-EIO,-EIO,-EIO};
 for(unsigned i=0;i<9;i++){response=statuses[i];assert(bes_gpio_irq_call(3,16,1)==errors[i]);}
 response=0x30000;assert(bes_gpio_irq_call(4,0,0)==0x30000);
 response=1;assert(bes_gpio_irq_call(4,0,0)==-EIO);
 returned=0;assert(bes_gpio_irq_connect()==-ENOTSUP);
 assert(bes_gpio_irq_call(2,0,0)==-ENODEV);
 return 0;
}
