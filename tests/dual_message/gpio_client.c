/* SPDX-License-Identifier: Apache-2.0 */
/* x86_64 host trampolines at valid Thumb addresses test the real client path. */
#define _GNU_SOURCE
#include <assert.h>
#include <errno.h>
#include <stdint.h>
#include <string.h>
#include <sys/mman.h>
#include <bes2700yp_gpio.h>
#include <bes2700_dual_boot.h>
static uint32_t returned=0x34000000;
static unsigned calls;
static int response, corrupt;
static int32_t discover(uint32_t op, uint32_t abi)
{ assert(op==9 && abi==4); calls++;return (int32_t)returned; }
static int32_t dispatch(uint32_t op, uint32_t address, uint32_t bytes)
{
 assert(op==1 && bytes==96 && address==BES_RESOURCE_RAM_START);calls++;
 struct bes_gpio_io *io=(void *)(uintptr_t)address;
 assert(io->abi==4 && io->bytes==96 && io->resource==4 && !io->pin && !io->value);
 for(unsigned i=0;i<3;i++) assert(!io->reserved[i]);
 io->snapshot=(struct bes_gpio_snapshot){.abi=4,.bytes=64,.phase=3,.pins=0x33000,.inputs=0x33000};
 switch(corrupt) {
 case 1:io->snapshot.bytes=32;break;
 case 2:io->snapshot.abi=3;break;
 case 3:io->snapshot.phase=6;break;
 case 4:io->snapshot.fault=2;break;
 case 5:io->snapshot.pins=0;break;
 case 6:io->snapshot.inputs=1;break;
 case 7:io->snapshot.directions=1;break;
 case 8:io->snapshot.outputs=1;break;
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
 struct bes_gpio_io *io=map(BES_RESOURCE_RAM_START);
 *d=(struct bes_resource_descriptor){BES_RESOURCE_MAGIC,4,32,8,0x14000021,96,64,0};
 assert(bes_gpio_call(1,0,0,io)==-ENODEV && !calls);
 root->magic=0;assert(bes_gpio_connect()==-ENODEV && !calls);root->magic=DUAL_SERVICE_MAGIC;
 uint32_t invalid[]={0,0xffffffff,0x20540000,0x34000001,0x347fffe4};
 for(unsigned i=0;i<sizeof(invalid)/4;i++) { returned=invalid[i];assert(bes_gpio_connect()==-ENOTSUP); }
 returned=0x34000000;d->abi=1;assert(bes_gpio_connect()==-ENOTSUP);d->abi=4;
 assert(!bes_gpio_connect());unsigned before=calls;
 assert(bes_gpio_call(3,12,1,io)==-ENOTSUP && calls==before);
 assert(bes_gpio_call(1,0,0,(void *)0x2055bfa4)==-EINVAL && calls==before);
 assert(!bes_gpio_call(1,0,0,io) && io->snapshot.pins==0x33000);
 int statuses[]={-1,-2,-3,-4,-5,-6,123};
 int errors[]={-EINVAL,-ENOTSUP,-EPERM,-EBUSY,-ENODEV,-EIO,-EIO};
 for(unsigned i=0;i<7;i++) { response=statuses[i];assert(bes_gpio_call(1,0,0,io)==errors[i]); }
 response=0;for(corrupt=1;corrupt<=8;corrupt++) assert(bes_gpio_call(1,0,0,io)==-EIO);corrupt=0;
 returned=0;assert(bes_gpio_connect()==-ENOTSUP);assert(bes_gpio_call(1,0,0,io)==-ENODEV);
 return 0;
}
