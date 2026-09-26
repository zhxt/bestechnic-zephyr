/* Copyright The Zephyr Project Contributors */
/* SPDX-License-Identifier: Apache-2.0 */

#include "shim.h"
#include "../../bsp/drivers/mbox/mbox_bes2700.c"

#ifdef TEST_BTH
#define SYS_ADDR 0x40000134U /* model-local */
#define BTH_ADDR 0x500000a0U /* model-peer */
#define TEST_RX_IRQ 39U
#undef SYS_RX_MASK
#undef SYS_TX_MASK
#undef SYS_RX_ACTIVE
#undef SYS_TX_ACTIVE
#define SYS_RX_MASK BTH_RX_MASK
#define SYS_TX_MASK BTH_TX_MASK
#define SYS_RX_ACTIVE BTH_RX_ACTIVE
#define SYS_TX_ACTIVE BTH_TX_ACTIVE
#else
#define SYS_ADDR 0x500000a0U
#define BTH_ADDR 0x40000134U
#define TEST_RX_IRQ 41U
#endif

static uint32_t masks;
static uint32_t kicks;
static uint32_t callbacks;
static uint32_t writes;
static bool incoming;
static bool outgoing;
static bool completed;
static bool rx_enabled;
static bool reply_in_callback;
#ifdef CONFIG_BES2700_M55_RESTART
static unsigned cleared;
static bool tx_enabled;
static bool stuck_done;
static void NVIC_ClearPendingIRQ(unsigned int irq) { assert(irq==TEST_RX_IRQ || irq==99);cleared++; }
#endif
static struct bes2700_mbox_data state;
static void connect_test(const struct device *dev) { (void)dev; }
static const struct bes2700_mbox_config config = {
	#ifdef TEST_BTH
 .endpoint_bth = true, .sys = BTH_ADDR, .bth = SYS_ADDR,
#else
 .endpoint_bth = false, .sys = SYS_ADDR, .bth = BTH_ADDR,
#endif
 .rx_irq = TEST_RX_IRQ, .connect = connect_test,
#ifdef CONFIG_BES2700_M55_RESTART
 .tx_irq=99,
#endif
};
static const struct device dev = {.config = &config, .data = &state};

static void irq_enable(unsigned int irq) {
#ifdef CONFIG_BES2700_M55_RESTART
 if(irq==99) { tx_enabled=true;return; }
#endif
 assert(irq == TEST_RX_IRQ); rx_enabled = true;
}
static void irq_disable(unsigned int irq) {
#ifdef CONFIG_BES2700_M55_RESTART
 if(irq==99) { tx_enabled=false;return; }
#endif
 assert(irq == TEST_RX_IRQ); rx_enabled = false;
}

static uint32_t sys_read32(uintptr_t addr)
{
#ifdef CONFIG_BES2700_M55_RESTART
 if(addr==BTH_ADDR) { return incoming?BTH_TX_IND:0; }
#endif
	if (addr == SYS_ADDR) {
		return masks |
#ifdef CONFIG_BES2700_M55_RESTART
            (outgoing?SYS_TX_IND:0) | ((completed || stuck_done)?SYS_TX_DONE:0) |
#endif
            (incoming && (masks & SYS_RX_MASK) ? SYS_RX_ACTIVE : 0U) |
			(completed && (masks & SYS_TX_MASK) ? SYS_TX_ACTIVE : 0U);
	}
	assert(addr == SYS_ADDR + 4U || addr == BTH_ADDR + 4U);
	return 0U;
}

static void sys_write32(uint32_t value, uintptr_t addr)
{
	writes++;
	if (addr == SYS_ADDR || addr == SYS_ADDR + 4U) {
		/* No write is allowed to touch channel 0 or any unrelated CMU bit. */
		assert((value & ~(SYS_TX_IND | SYS_TX_DONE | SYS_RX_MASK | SYS_TX_MASK)) == 0U);
		if (addr == SYS_ADDR) {
			masks |= value & (SYS_RX_MASK | SYS_TX_MASK);
			if ((value & SYS_TX_IND) != 0U) {
				assert(!outgoing);
				outgoing = true;
				kicks++;
			}
		} else {
			masks &= ~(value & (SYS_RX_MASK | SYS_TX_MASK));
			if ((value & SYS_TX_DONE) != 0U) { completed = false; }
			if ((value & SYS_TX_IND) != 0U) { outgoing = false; }
		}
	} else {
		assert(addr == BTH_ADDR + 4U);
#ifdef CONFIG_BES2700_M55_RESTART
        assert(value==BTH_TX_IND || value==(BTH_TX_IND|SYS_TX_DONE));
#else
        assert(value == BTH_TX_IND);
#endif
		incoming = false;
	}
}

static void receive(const struct device *device, uint32_t channel, void *context,
		    struct mbox_msg *message)
{
	assert(device == &dev && channel == 0U && context == &callbacks && message == NULL);
	assert(!incoming && state.lock.held == 0);
	callbacks++;
	if (reply_in_callback) { assert(bes2700_send(device, 0U, NULL) == 0); }
}

static void reset(void)
{
	memset(&state, 0, sizeof(state));
	masks = kicks = callbacks = writes = 0U;
	incoming = outgoing = completed = rx_enabled = reply_in_callback = false;
	assert(bes2700_init(&dev) == 0);
	assert(bes2700_api.mtu_get(&dev) == 0);
	assert(bes2700_api.max_channels_get(&dev) == 1U);
	assert(bes2700_register(&dev, 0U, receive, &callbacks) == 0);
}

static void done(void)
{
	assert(outgoing);
	outgoing = false;
	completed = true;
	tx_isr(&dev);
}

int main(void)
{
	reset();
	uint32_t previous = writes;
	struct mbox_msg invalid = {0};
	assert(bes2700_send(&dev, 1U, NULL) == -EINVAL);
	assert(bes2700_send(&dev, 0U, &invalid) == -EMSGSIZE);
	assert(bes2700_register(&dev, 1U, receive, NULL) == -EINVAL);
	assert(bes2700_enable(&dev, 1U, true) == -EINVAL);
	assert(writes == previous);

	/* Busy calls merge; completion must replay once, then become idle. */
	for (uint32_t i = 0U; i < 32U; i++) { assert(bes2700_send(&dev, 0U, NULL) == 0); }
	assert(kicks == 1U && state.stats.queued == 31U);
	done();
	assert(kicks == 2U && state.busy && !state.pending);
	done();
	assert(!state.busy && !outgoing && state.stats.done == 2U);

	/* Pending receive survives disable/re-enable and is cleared before callback. */
	reset();
	assert(bes2700_enable(&dev, 0U, false) == 0);
	incoming = true;
	assert(!rx_enabled && (sys_read32(SYS_ADDR) & SYS_RX_ACTIVE) == 0U);
	assert(bes2700_enable(&dev, 0U, true) == 0);
	assert(rx_enabled && (sys_read32(SYS_ADDR) & SYS_RX_ACTIVE) != 0U);
	reply_in_callback = true;
	rx_isr(&dev);
	assert(callbacks == 1U && kicks == 1U && !incoming);
	done();
	assert(bes2700_enable(&dev, 0U, false) == 0);
	assert(bes2700_register(&dev, 0U, NULL, NULL) == 0);
	assert(bes2700_enable(&dev, 0U, true) == 0);
	incoming = true;
	rx_isr(&dev);
	assert(callbacks == 1U && !incoming);

	/* Arrival before and after DONE must leave no stranded pending send. */
	reset();
	for (uint32_t i = 0U; i < 10000U; i++) {
		assert(bes2700_send(&dev, 0U, NULL) == 0);
		if ((i % 2U) == 0U) { assert(bes2700_send(&dev, 0U, NULL) == 0); }
		while (state.busy) { done(); }
		assert(!state.pending);
	}
	assert(state.stats.requests == 15000U && state.stats.done == 15000U);
	struct bes2700_mbox_stats stats;
	bes2700_mbox_get_stats(&dev, &stats);
	assert(stats.done == kicks && stats.spurious == 0U);
	completed = true;
	tx_isr(&dev);
	assert(state.stats.spurious == 1U && !state.busy);
#ifdef CONFIG_BES2700_M55_RESTART
 for(unsigned round=0;round<11;round++) {
  incoming=completed=true;
  assert(bes2700_send(&dev,0,NULL)==0);
  assert(bes2700_send(&dev,0,NULL)==0);
  unsigned old=cleared;
  assert(bes2700_mbox_reset(&dev)==0 && cleared==old+2);
  assert(!incoming && !outgoing && !completed && !rx_enabled && !tx_enabled);
  assert(!state.busy && !state.pending && !state.callback && state.resetting);
  assert(state.stats.requests==0 && state.stats.spurious==0);
  assert(bes2700_send(&dev,0,NULL)==-EBUSY);
  assert(bes2700_mbox_reset(&dev)==0); /* idempotent while held reset */
  assert(bes2700_mbox_resume(&dev)==0 && tx_enabled);
  assert(bes2700_register(&dev,0,receive,&callbacks)==0);
  assert(bes2700_enable(&dev,0,true)==0);
  assert(bes2700_send(&dev,0,NULL)==0);done();
  assert(state.stats.requests==1 && state.stats.done==1);
 }
 /* Failed readback must leave both interrupts and transmission gated. */
 stuck_done=true;
 assert(bes2700_mbox_reset(&dev)==-EIO);
 struct bes2700_mbox_raw raw;
 bes2700_mbox_get_raw(&dev,&raw);
 assert(raw.local==SYS_TX_DONE && raw.peer==0);
 assert(bes2700_send(&dev,0,NULL)==-EBUSY);
 assert(bes2700_enable(&dev,0,true)==-EBUSY);
 assert(bes2700_mbox_resume(&dev)==-EIO);
 assert(!rx_enabled && !tx_enabled && state.resetting);
 stuck_done=false;
 assert(bes2700_mbox_reset(&dev)==0);
 /* New peer notification between clear and resume must survive. */
 incoming=true;
 unsigned before=callbacks;
 assert(bes2700_mbox_resume(&dev)==0);
 assert(bes2700_register(&dev,0,receive,&callbacks)==0);
 assert(bes2700_enable(&dev,0,true)==0);
 rx_isr(&dev);
 assert(callbacks==before+1 && !incoming);
#endif
	return 0;
}
