/* SPDX-License-Identifier: Apache-2.0 */
#define _GNU_SOURCE
#include <assert.h>
#include <stdint.h>
#include <string.h>
#include <sys/mman.h>
#define BES2700YP_BOOTSTRAP_ARCH_H
#define BES_RESOURCE_HOST_TEST
static uint32_t ipsr,control,mask,basepri,phase=3,calls;
static int failure;
static struct {uint32_t ISER[2];} nvic;
#define NVIC (&nvic)
static uint32_t __get_IPSR(void){return ipsr;}
static uint32_t __get_CONTROL(void){return control;}
static uint32_t __get_PRIMASK(void){return mask;}
static uint32_t __get_BASEPRI(void){return basepri;}
static void __disable_irq(void){mask=1;}
static void __set_PRIMASK(uint32_t v){mask=v;}
#include <bestechnic/bes2700yp/hw.h>
uint32_t dual_service_phase(void){return phase;}
int bes2700yp_gpio_irq_claim(void){assert(!mask);calls++;return failure;}
int bes2700yp_gpio_irq_config(uint32_t pin,uint32_t mode)
{assert(!mask && (pin==16||pin==17) && mode<3);calls++;return failure;}
int32_t bes2700yp_gpio_irq_ack(void){assert(!mask && ipsr==60);calls++;return failure?failure:0x10000;}
int bes2700yp_gpio_irq_read(struct bes2700yp_gpio_irq_state *s)
{assert(!mask && !ipsr);calls++;*s=(struct bes2700yp_gpio_irq_state){.enabled=0x30000};return failure;}
#include "../../platforms/bes2700yp/boot/bootstrap/gpio_irq_service.c"
static struct bes_gpio_irq_io *io=(void *)BES_RESOURCE_RAM_START;
int main(void)
{
 assert(mmap(io,4096,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS|MAP_FIXED_NOREPLACE,-1,0)==io);
 *io=(struct bes_gpio_irq_io){.abi=5,.bytes=96};
 assert(!bes_gpio_irq_dispatch(1,(uint32_t)(uintptr_t)io,96));assert(io->state.enabled==0x30000);
 assert(!bes_gpio_irq_dispatch(2,0,0));assert(!bes_gpio_irq_dispatch(3,16,1));
 uint32_t prior=calls;
 mask=1;assert(bes_gpio_irq_dispatch(2,0,0)==-6);mask=0;
 basepri=1;assert(bes_gpio_irq_dispatch(2,0,0)==-6);basepri=0;
 control=1;assert(bes_gpio_irq_dispatch(2,0,0)==-6);control=0;
 NVIC->ISER[1]=1U<<12;assert(bes_gpio_irq_dispatch(1,(uint32_t)(uintptr_t)io,96)==-6);NVIC->ISER[1]=0;
 assert(bes_gpio_irq_dispatch(4,0,0)==-1);assert(bes_gpio_irq_dispatch(3,18,1)==-1);
 assert(bes_gpio_irq_dispatch(3,16,3)==-1);
 io->reserved[5]=1;assert(bes_gpio_irq_dispatch(1,(uint32_t)(uintptr_t)io,96)==-1);io->reserved[5]=0;
 assert(calls==prior);
 for(unsigned p=0;p<6;p++){
  phase=p;assert(bes_gpio_irq_dispatch(2,0,0)==(p==3||p==4?0:-5));
 }
 phase=3;ipsr=15;assert(bes_gpio_irq_dispatch(4,0,0)==-6);ipsr=60;
 assert(bes_gpio_irq_dispatch(4,0,0)==0x10000);
 assert(!bes_gpio_irq_dispatch(3,16,0));
 assert(bes_gpio_irq_dispatch(3,16,1)==-6);
 assert(bes_gpio_irq_dispatch(1,(uint32_t)(uintptr_t)io,96)==-6);
 assert(bes_gpio_irq_dispatch(2,0,0)==-6);
 ipsr=0;irq_busy=1;prior=calls;assert(bes_gpio_irq_dispatch(2,0,0)==-6 && calls==prior && !mask);irq_busy=0;
 for(int e=-1;e>=-5;e--){failure=e;assert(bes_gpio_irq_dispatch(3,16,1)==e && !irq_busy && !mask);}
 return 0;
}
