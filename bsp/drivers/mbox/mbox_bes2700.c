/* Copyright The Zephyr Project Contributors */
/* SPDX-License-Identifier: Apache-2.0 */

#define DT_DRV_COMPAT bestechnic_bes2700_mbox

#include <zephyr/device.h>
#include <zephyr/drivers/mbox.h>
#include <zephyr/irq.h>
#include <zephyr/kernel.h>
#include <zephyr/sys/barrier.h>
#include <zephyr/sys/sys_io.h>
#include <bes2700_mbox.h>
#ifdef CONFIG_BES2700_M55_RESTART
#include <cmsis_core.h>
#endif

/* Channel 1 fields from the BES2700 SYS/BTH CMU register maps. */
#define IRQ_CLR_OFFSET 4U
#define SYS_TX_IND BIT(3)
#define SYS_TX_DONE BIT(1)
#define SYS_RX_MASK BIT(14)
#define SYS_TX_MASK BIT(16)
#define SYS_RX_ACTIVE BIT(22)
#define SYS_TX_ACTIVE BIT(24)
#define BTH_TX_IND BIT(3)
#define BTH_RX_MASK BIT(5)
#define BTH_TX_MASK BIT(7)
#define BTH_RX_ACTIVE BIT(14)
#define BTH_TX_ACTIVE BIT(16)

struct bes2700_mbox_config {
	bool endpoint_bth;
	uintptr_t sys;
	uintptr_t bth;
	unsigned int rx_irq;
#ifdef CONFIG_BES2700_M55_RESTART
	unsigned int tx_irq;
#endif
	void (*connect)(const struct device *dev);
};

struct bes2700_mbox_data {
	struct k_spinlock lock;
	mbox_callback_t callback;
	void *user_data;
	bool enabled;
	bool busy;
	bool pending;
#ifdef CONFIG_BES2700_M55_RESTART
	bool resetting;
	bool reset_failed;
#endif
	struct bes2700_mbox_stats stats;
};

static uintptr_t local(const struct bes2700_mbox_config *cfg)
{ return cfg->endpoint_bth ? cfg->bth : cfg->sys; }
static uintptr_t peer(const struct bes2700_mbox_config *cfg)
{ return cfg->endpoint_bth ? cfg->sys : cfg->bth; }
static uint32_t rx_mask(const struct bes2700_mbox_config *cfg)
{ return cfg->endpoint_bth ? BTH_RX_MASK : SYS_RX_MASK; }
static uint32_t tx_mask(const struct bes2700_mbox_config *cfg)
{ return cfg->endpoint_bth ? BTH_TX_MASK : SYS_TX_MASK; }
static uint32_t rx_active(const struct bes2700_mbox_config *cfg)
{ return cfg->endpoint_bth ? BTH_RX_ACTIVE : SYS_RX_ACTIVE; }
static uint32_t tx_active(const struct bes2700_mbox_config *cfg)
{ return cfg->endpoint_bth ? BTH_TX_ACTIVE : SYS_TX_ACTIVE; }

static void write_flush(uint32_t bits, uintptr_t address)
{
	sys_write32(bits, address);
	(void)sys_read32(address);
	barrier_dsync_fence_full();
}

static void kick(const struct device *dev)
{
	const struct bes2700_mbox_config *cfg = dev->config;
	struct bes2700_mbox_data *data = dev->data;

	data->busy = true;
	data->stats.kicks++;
	barrier_dsync_fence_full();
	write_flush(SYS_TX_IND, local(cfg));
}

static int bes2700_send(const struct device *dev, uint32_t channel,
			const struct mbox_msg *msg)
{
	struct bes2700_mbox_data *data = dev->data;

	if (channel != 0U) {
		return -EINVAL;
	}
	if (msg != NULL) {
		return -EMSGSIZE;
	}
	k_spinlock_key_t key = k_spin_lock(&data->lock);

#ifdef CONFIG_BES2700_M55_RESTART
	if (data->resetting) {
		k_spin_unlock(&data->lock, key);
		return -EBUSY;
	}
#endif
	data->stats.requests++;
	if (data->busy) {
		data->pending = true;
		data->stats.queued++;
	} else {
		kick(dev);
	}
	k_spin_unlock(&data->lock, key);
	return 0;
}

static void rx_isr(const struct device *dev)
{
	const struct bes2700_mbox_config *cfg = dev->config;
	struct bes2700_mbox_data *data = dev->data;
	k_spinlock_key_t key = k_spin_lock(&data->lock);
	mbox_callback_t callback = NULL;
	void *context = NULL;

	if (data->enabled && (sys_read32(local(cfg)) & rx_active(cfg)) != 0U) {
		/* Clearing the peer's IND also acknowledges receipt to the peer. */
		write_flush(BTH_TX_IND, peer(cfg) + IRQ_CLR_OFFSET);
		data->stats.rx++;
		callback = data->callback;
		context = data->user_data;
	} else {
		data->stats.spurious++;
	}
	k_spin_unlock(&data->lock, key);
	if (callback != NULL) {
		callback(dev, 0U, context, NULL);
	}
}

static void tx_isr(const struct device *dev)
{
	const struct bes2700_mbox_config *cfg = dev->config;
	struct bes2700_mbox_data *data = dev->data;
	k_spinlock_key_t key = k_spin_lock(&data->lock);

	if ((sys_read32(local(cfg)) & tx_active(cfg)) != 0U) {
		write_flush(SYS_TX_DONE, local(cfg) + IRQ_CLR_OFFSET);
		if (data->busy) {
			data->stats.done++;
			data->busy = false;
			if (data->pending) {
				data->pending = false;
				kick(dev);
			}
		} else {
			data->stats.spurious++;
		}
	} else {
		data->stats.spurious++;
	}
	k_spin_unlock(&data->lock, key);
}

static int bes2700_register(const struct device *dev, uint32_t channel,
			    mbox_callback_t callback, void *user_data)
{
	struct bes2700_mbox_data *data = dev->data;

	if (channel != 0U) {
		return -EINVAL;
	}
	k_spinlock_key_t key = k_spin_lock(&data->lock);

	data->callback = callback;
	data->user_data = user_data;
	k_spin_unlock(&data->lock, key);
	return 0;
}

static int bes2700_enable(const struct device *dev, uint32_t channel, bool enable)
{
	const struct bes2700_mbox_config *cfg = dev->config;
	struct bes2700_mbox_data *data = dev->data;

	if (channel != 0U) {
		return -EINVAL;
	}
	k_spinlock_key_t key = k_spin_lock(&data->lock);

#ifdef CONFIG_BES2700_M55_RESTART
	if (enable && data->resetting) {
		k_spin_unlock(&data->lock, key);
		return -EBUSY;
	}
#endif
	data->enabled = enable;
	if (enable) {
		/* Preserve a pending IND received while disabled. */
		write_flush(rx_mask(cfg), local(cfg));
		irq_enable(cfg->rx_irq);
	} else {
		irq_disable(cfg->rx_irq);
		write_flush(rx_mask(cfg), local(cfg) + IRQ_CLR_OFFSET);
	}
	k_spin_unlock(&data->lock, key);
	return 0;
}

void bes2700_mbox_get_stats(const struct device *dev, struct bes2700_mbox_stats *out)
{
	struct bes2700_mbox_data *data = dev->data;
	k_spinlock_key_t key = k_spin_lock(&data->lock);

	*out = data->stats;
	k_spin_unlock(&data->lock, key);
}

static int bes2700_mtu(const struct device *dev)
{
	ARG_UNUSED(dev);
	return 0;
}

static uint32_t bes2700_channels(const struct device *dev)
{
	ARG_UNUSED(dev);
	return 1U;
}

static int bes2700_init(const struct device *dev)
{
	const struct bes2700_mbox_config *cfg = dev->config;

	write_flush(rx_mask(cfg) | tx_mask(cfg), local(cfg) + IRQ_CLR_OFFSET);
	write_flush(SYS_TX_DONE | SYS_TX_IND, local(cfg) + IRQ_CLR_OFFSET);
	write_flush(tx_mask(cfg), local(cfg));
	cfg->connect(dev);
	return 0;
}

#ifdef CONFIG_BES2700_M55_RESTART
int bes2700_mbox_suspend(const struct device *dev)
{
 const struct bes2700_mbox_config *cfg=dev->config;
 struct bes2700_mbox_data *data=dev->data;
 k_spinlock_key_t key=k_spin_lock(&data->lock);
 data->resetting=true;data->enabled=false;
 irq_disable(cfg->rx_irq);irq_disable(cfg->tx_irq);
 write_flush(rx_mask(cfg)|tx_mask(cfg),local(cfg)+IRQ_CLR_OFFSET);
 k_spin_unlock(&data->lock,key);
 return 0;
}

int bes2700_mbox_reset(const struct device *dev)
{
 const struct bes2700_mbox_config *cfg=dev->config;
 struct bes2700_mbox_data *data=dev->data;
 k_spinlock_key_t key=k_spin_lock(&data->lock);
 data->resetting=true;data->enabled=false;
 irq_disable(cfg->rx_irq);irq_disable(cfg->tx_irq);
 write_flush(rx_mask(cfg)|tx_mask(cfg),local(cfg)+IRQ_CLR_OFFSET);
 /* Peer CPU is held reset. Both raw IND/DONE fields share bits 3/1. */
 write_flush(SYS_TX_IND|SYS_TX_DONE,peer(cfg)+IRQ_CLR_OFFSET);
 write_flush(SYS_TX_IND|SYS_TX_DONE,local(cfg)+IRQ_CLR_OFFSET);
 NVIC_ClearPendingIRQ(cfg->rx_irq);NVIC_ClearPendingIRQ(cfg->tx_irq);
 uint32_t raw=sys_read32(local(cfg))|sys_read32(peer(cfg));
 data->reset_failed=(raw&(SYS_TX_IND|SYS_TX_DONE))!=0;
 data->busy=false;data->pending=false;
 data->stats=(struct bes2700_mbox_stats){0};
 data->callback=NULL;data->user_data=NULL;
 int rc=data->reset_failed ? -EIO:0;
 k_spin_unlock(&data->lock,key);
 return rc;
}
int bes2700_mbox_resume(const struct device *dev)
{
 const struct bes2700_mbox_config *cfg=dev->config;
 struct bes2700_mbox_data *data=dev->data;
 k_spinlock_key_t key=k_spin_lock(&data->lock);
 if(data->reset_failed) { k_spin_unlock(&data->lock,key);return -EIO; }
 data->resetting=false;
 write_flush(tx_mask(cfg),local(cfg));irq_enable(cfg->tx_irq);
 k_spin_unlock(&data->lock,key);return 0;
}

void bes2700_mbox_get_raw(const struct device *dev, struct bes2700_mbox_raw *out)
{
	const struct bes2700_mbox_config *cfg = dev->config;
	struct bes2700_mbox_data *data = dev->data;
	k_spinlock_key_t key = k_spin_lock(&data->lock);

	out->local = sys_read32(local(cfg));
	out->peer = sys_read32(peer(cfg));
	k_spin_unlock(&data->lock, key);
}
#endif

static DEVICE_API(mbox, bes2700_api) = {
	.send = bes2700_send,
	.register_callback = bes2700_register,
	.mtu_get = bes2700_mtu,
	.max_channels_get = bes2700_channels,
	.set_enabled = bes2700_enable,
};

#define BES2700_DEFINE(inst)                                                             \
	static void connect_##inst(const struct device *dev)                             \
	{                                                                                \
		ARG_UNUSED(dev);                                                         \
		IRQ_CONNECT(DT_INST_IRQ_BY_NAME(inst, rx, irq),                            \
			    DT_INST_IRQ_BY_NAME(inst, rx, priority), rx_isr,                \
			    DEVICE_DT_INST_GET(inst), 0);                                 \
		IRQ_CONNECT(DT_INST_IRQ_BY_NAME(inst, tx_done, irq),                       \
			    DT_INST_IRQ_BY_NAME(inst, tx_done, priority), tx_isr,           \
			    DEVICE_DT_INST_GET(inst), 0);                                 \
		irq_enable(DT_INST_IRQ_BY_NAME(inst, tx_done, irq));                       \
	}                                                                                \
	static const struct bes2700_mbox_config config_##inst = {                         \
		.endpoint_bth = DT_INST_PROP(inst, endpoint_bth),                         \
		.sys = DT_INST_REG_ADDR_BY_NAME(inst, sys),                               \
		.bth = DT_INST_REG_ADDR_BY_NAME(inst, bth),                               \
		.rx_irq = DT_INST_IRQ_BY_NAME(inst, rx, irq),                             \
		BES2700_RESTART_CONFIG(inst)                                            \
		.connect = connect_##inst,                                                \
	};                                                                               \
	static struct bes2700_mbox_data data_##inst;                                      \
	DEVICE_DT_INST_DEFINE(inst, bes2700_init, NULL, &data_##inst, &config_##inst,       \
			      PRE_KERNEL_1, CONFIG_MBOX_INIT_PRIORITY, &bes2700_api);

#ifdef CONFIG_BES2700_M55_RESTART
#define BES2700_RESTART_CONFIG(inst) .tx_irq = DT_INST_IRQ_BY_NAME(inst, tx_done, irq),
#else
#define BES2700_RESTART_CONFIG(inst)
#endif
DT_INST_FOREACH_STATUS_OKAY(BES2700_DEFINE)
