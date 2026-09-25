/* Copyright The Zephyr Project Contributors */
/* SPDX-License-Identifier: Apache-2.0 */
/* Included by the isolated SDK main.cpp, after loader callback declarations. */
#ifndef BES2700_IPC_MONITOR_H_
#define BES2700_IPC_MONITOR_H_
#include "bes2700_doorbell.h"
#include "bes2700_ipc_protocol.h"
#include "bes2700_ipc_mpu.h"
#include "hal_sys2bth.h"
#include "mpu.h"

#if defined(DSP_M55_TRC_TO_MCU) || defined(DSP_HIFI4_TRC_TO_MCU) || \
    defined(DMA_AUDIO_APP) || defined(MCPP_ALGO_M55) || defined(MCPP_ALGO_HIFI)
#error "Message tests require exclusive SYS-BTH channel 1 and M55 ownership"
#endif
static_assert(sizeof(struct bi_ring) == 4096, "wire ring layout");
static_assert(sizeof(struct bi_shared) == BI_BYTES, "shared memory layout");
static_assert(sizeof(struct bes2700_doorbell) == 88, "diagnostic layout");
static volatile struct bi_shared *const ipc_mem = (volatile struct bi_shared *)BI_BASE;
static volatile uint32_t ipc_rx_irq, ipc_tx_done;
static uint32_t ipc_sent;
static osThreadId ipc_thread;

static void ipc_rx(uint32_t core, uint32_t id)
{
    (void)core;
    if (id == HAL_SYS2BTH_ID_1) { ipc_rx_irq++; osSignalSet(ipc_thread, 1); }
}
static void ipc_done(uint32_t core, uint32_t id)
{
    (void)core;
    if (id == HAL_SYS2BTH_ID_1) { ipc_tx_done++; osSignalSet(ipc_thread, 1); }
}

static bool ipc_snapshot(struct bes2700_doorbell *s)
{
    volatile struct bes2700_doorbell *p = (volatile struct bes2700_doorbell *)BI_DIAG;
    for (unsigned int i = 0; i < 8; i++) {
        if (p->magic != BI_MAGIC || p->version != BI_VERSION || p->size != sizeof(*s)) { return false; }
        uint32_t seq = p->seq;
        if (seq & 1U) { continue; }
        __DMB();
#define READ(name) s->name = p->name;
        BES_DB_FIELDS(READ)
#undef READ
        __DMB();
        if (seq == p->seq && p->magic == BI_MAGIC) { return true; }
    }
    return false;
}

static bool ipc_stage(uint32_t stage, struct bes2700_doorbell *s)
{
    uint32_t start = hal_sys_timer_get();
    do {
        if (ipc_snapshot(s)) {
            if (s->stage == stage) { return true; }
            if (s->stage == BI_FAILED) { return false; }
        }
        osDelay(1);
    } while (TICKS_TO_MS(hal_sys_timer_get() - start) < 30000U);
    return false;
}

static bool ipc_notify(bool *pending)
{
    if (!*pending || ipc_sent != ipc_tx_done) { return true; }
    if (hal_sys2bth_ipc_notify_interrupt_core(HAL_SYS2BTH_ID_1)) { return false; }
    ipc_sent++;
    *pending = false;
    return true;
}

static bool ipc_drain(void)
{
    uint32_t start = hal_sys_timer_get();
    while (ipc_sent != ipc_tx_done) {
        if (TICKS_TO_MS(hal_sys_timer_get() - start) > 5000) { return false; }
        osSignalWait(1, 1);
    }
    return true;
}

/* Reject partial overlaps before the SDK's asserting mpu_set implementation.
 * NO_MPU_DEFAULT_MAP builds support splitting a containing region.
 */
static bool ipc_map(uint32_t base, uint32_t size)
{
    uint32_t key = int_lock_global(), saved = MPU->RNR;
    bool permitted = true;
    for (uint32_t i = 0; i < ((MPU->TYPE >> 8) & 255U); i++) {
        MPU->RNR = i;
        uint32_t b = MPU->RBAR & ~31U, l = MPU->RLAR;
        if (!(l & 1U) || b >= base + size || (l | 31U) < base) { continue; }
#ifdef NO_MPU_DEFAULT_MAP
        permitted = permitted && b <= base && (l | 31U) >= base + size - 1U;
#else
        permitted = permitted && b == base && (l | 31U) == base + size - 1U;
#endif
    }
    MPU->RNR = saved;
    int rc = permitted ? mpu_set(base, size, MPU_ATTR_READ_WRITE, MEM_ATTR_NORMAL_NON_CACHEABLE) : -1;
    bool ok = rc == 0 && bi_mpu_nc(base, size);
    __DSB(); __ISB();
    int_unlock_global(key);
    return ok;
}

static bool ipc_open(void)
{
    ipc_sent = 0; ipc_tx_done = 0; ipc_rx_irq = 0;
    return !hal_sys2bth_opened(HAL_SYS2BTH_ID_1) &&
        hal_sys2bth_ipc_notify_open(HAL_SYS2BTH_ID_1, ipc_rx, ipc_done) == 0 &&
        hal_sys2bth_ipc_notify_start_recv(HAL_SYS2BTH_ID_1) == 0;
}

static int ipc_session(uint32_t session, struct bes2700_doorbell *s)
{
    if (!ipc_stage(BI_READY, s)) { return 10; }
    if (s->kicks != ZEPHYR_M55_IPC_MODE || s->requests != ZEPHYR_M55_IPC_COUNT ||
        s->reserved1 != 1 || s->build != ZEPHYR_M55_IPC_BUILD_ID) { return 11; }
    TRACE(3, "zephyr_ipc ready session=%u build=%08x nc=%u !", session, s->build, s->reserved1);
    if (!bi_guards_ok(&ipc_mem->b2m) || !bi_guards_ok(&ipc_mem->m2b) ||
        ipc_mem->b2m.head || ipc_mem->b2m.tail || ipc_mem->m2b.head || ipc_mem->m2b.tail) { return 12; }
    struct bi_frame f;
    bi_make(&f, session, 1, BI_HELLO, 0, 0); f.crc ^= 1;
    if (bi_push(&ipc_mem->b2m, &f) != BI_OK) { return 13; }
    bi_make(&f, session - 1U, 1, BI_HELLO, 0, 0);
    if (bi_push(&ipc_mem->b2m, &f) != BI_OK) { return 14; }
    uint32_t tx = 1, rx = 1, total = ZEPHYR_M55_IPC_COUNT + 2U;
    /* Hold M55 behind GO, fill every slot, then prove FULL changes no index. */
    for (; tx <= BI_DEPTH - 2U; tx++) {
        uint32_t length = tx == 1 ? 0 : (ZEPHYR_M55_IPC_MODE == 2 ? BI_PAYLOAD : tx % 97U);
        bi_make(&f, session, tx, tx == 1 ? BI_HELLO : BI_DATA, length, 0);
        if (bi_push(&ipc_mem->b2m, &f) != BI_OK) { return 15; }
    }
    uint32_t held = ipc_mem->b2m.head;
    if (bi_push(&ipc_mem->b2m, &f) != BI_FULL || ipc_mem->b2m.head != held) { return 16; }
    TRACE(1, "zephyr_ipc full session=%u unchanged=1 !", session);
    __DMB(); ipc_mem->b2m.go = session; __DMB();
    bool pending = true;
    uint32_t last = hal_sys_timer_get();
    while (rx <= total) {
        bool progressed = false;
        while (tx <= total) {
            uint32_t type = tx == total ? BI_FINISH : BI_DATA;
            uint32_t length = type == BI_FINISH ? 0 : (ZEPHYR_M55_IPC_MODE == 2 ? BI_PAYLOAD : tx % 97U);
            bi_make(&f, session, tx, type, length, 0);
            enum bi_rc rc = bi_push(&ipc_mem->b2m, &f);
            if (rc == BI_FULL) { break; }
            if (rc != BI_OK) { return 17; }
            tx++; pending = true; progressed = true;
        }
        if (!ipc_notify(&pending)) { return 18; }
        for (;;) {
            enum bi_rc rc = bi_pop(&ipc_mem->m2b, &f);
            if (rc == BI_EMPTY) { break; }
            uint32_t type = rx == 1 ? BI_HELLO : (rx == total ? BI_FINISH : BI_DATA);
            uint32_t length = type != BI_DATA ? 0 : (ZEPHYR_M55_IPC_MODE == 2 ? BI_PAYLOAD : rx % 97U);
            if (rc != BI_OK || rx > total || bi_validate(&f, session, rx) != BI_OK ||
                !bi_pattern_ok(&f, 1) || f.type != type || f.length != length) { return 19; }
            rx++; progressed = true;
            if ((rx - 2U) % 10000U == 0) {
                TRACE(2, "zephyr_ipc progress session=%u data=%u !", session, rx - 2U);
            }
        }
        if (progressed) { last = hal_sys_timer_get(); }
        if (TICKS_TO_MS(hal_sys_timer_get() - last) > 30000U) { return 20; }
        /* Queue indices are authoritative; signals are coalescing wake hints. */
        if (!progressed) { osSignalWait(1, 1); }
    }
    if (!ipc_drain() || !ipc_stage(BI_COMPLETE, s) || s->reserved0 != session ||
        s->progress != ZEPHYR_M55_IPC_COUNT || s->rx != total || s->done != total ||
        s->queued != 1 || s->spurious != 1 || s->error ||
        !bi_guards_ok(&ipc_mem->b2m) || !bi_guards_ok(&ipc_mem->m2b) ||
        ipc_mem->b2m.head != ipc_mem->b2m.tail || ipc_mem->m2b.head != ipc_mem->m2b.tail) { return 21; }
    TRACE(3, "zephyr_ipc counts session=%u tx=%u rx=%u !", session, total - 2U, total - 2U);
    TRACE(3, "zephyr_ipc checks session=%u crc=%u stale=%u guards=1 !", session, s->queued, s->spurious);
    bi_make(&f, session, total + 1U, BI_QUIESCE, 0, 0);
    if (bi_push(&ipc_mem->b2m, &f) != BI_OK) { return 22; }
    pending = true;
    if (!ipc_notify(&pending) || pending || !ipc_drain() ||
        !ipc_stage(BI_QUIESCED, s) || s->reserved0 != session) { return 23; }
    TRACE(1, "zephyr_ipc quiesced session=%u !", session);
    return 0;
}

static void zephyr_m55_heartbeat_thread(void const *argument)
{
    (void)argument;
    ipc_thread = osThreadGetId();
    struct bes2700_doorbell s = {};
    TRACE(3, "zephyr_ipc begin mode=%u count=%u restarts=%u !",
          ZEPHYR_M55_IPC_MODE, ZEPHYR_M55_IPC_COUNT, ZEPHYR_M55_IPC_RESTARTS);
    bool mapped = ipc_map(BI_BASE, BI_BYTES) && ipc_map(BI_DIAG, BI_DIAG_BYTES);
    TRACE(1, "zephyr_ipc bth_nc=%u !", mapped ? 1 : 0);
    int rc = mapped && ipc_open() ? 0 : 1;
    uint32_t complete = 0;
    for (uint32_t i = 0; rc == 0 && i <= ZEPHYR_M55_IPC_RESTARTS; i++) {
        uint32_t session = i + 1U;
        rc = ipc_session(session, &s);
        TRACE(3, "zephyr_ipc session=%u pass=%u rc=%d !", session, rc == 0 ? 1 : 0, rc);
        if (rc) { break; }
        complete++;
        if (i == ZEPHYR_M55_IPC_RESTARTS) { break; }
        /* Only this worker reads M55 RAM. Both channel-1 IRQs are closed while
         * the peer is still powered. Loader DMA is synchronous and has ended.
         * M55 has acknowledged QUIESCE and will never access the queues again.
         */
        if (hal_sys2bth_ipc_notify_close(HAL_SYS2BTH_ID_1) != 0) { rc = 30; break; }
        *(volatile uint32_t *)BI_DIAG = 0;
        __DSB();
        if (dsp_m55_close() != 0) { rc = 31; break; }
        TRACE(1, "zephyr_ipc off session=%u !", session);
        /* No M55 RAM/diagnostic/mailbox access until the loader returns. */
        osDelay(100);
        if (dsp_m55_open(zephyr_m55_rx_handler, zephyr_m55_tx_handler) != 0) { rc = 32; break; }
        TRACE(1, "zephyr_ipc on session=%u !", session + 1U);
        if (!ipc_open()) { rc = 33; break; }
    }
    TRACE(3, "zephyr_ipc result pass=%u sessions=%u rc=%d !", rc == 0 ? 1 : 0, complete, rc);
    for (;;) { osDelay(1000); }
}
#endif
