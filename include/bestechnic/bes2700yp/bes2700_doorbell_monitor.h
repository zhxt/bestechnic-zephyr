/* Copyright The Zephyr Project Contributors */
/* SPDX-License-Identifier: Apache-2.0 */
/* SDK BTH test service, included from platform/main/main.cpp. */
#ifndef BES2700_DOORBELL_MONITOR_H_
#define BES2700_DOORBELL_MONITOR_H_

#include "bes2700_doorbell.h"
#include "hal_sys2bth.h"

#if defined(DSP_M55_TRC_TO_MCU) || defined(DSP_HIFI4_TRC_TO_MCU) || \
    defined(DMA_AUDIO_APP) || defined(MCPP_ALGO_M55) || defined(MCPP_ALGO_HIFI)
#error "Doorbell test requires exclusive ownership of SYS-BTH hardware channel 1"
#endif

static_assert(sizeof(struct bes2700_doorbell) == 88, "Doorbell diagnostic size");
static volatile uint32_t doorbell_rx;
static volatile uint32_t doorbell_done;
static uint32_t doorbell_sent;
static osThreadId doorbell_thread;

static void doorbell_rx_irq(uint32_t core, uint32_t id)
{
    (void)core;
    if (id == HAL_SYS2BTH_ID_1) {
        doorbell_rx++;
        osSignalSet(doorbell_thread, 1);
    }
}

static void doorbell_done_irq(uint32_t core, uint32_t id)
{
    (void)core;
    if (id == HAL_SYS2BTH_ID_1) {
        doorbell_done++;
        osSignalSet(doorbell_thread, 1);
    }
}

static bool doorbell_snapshot(struct bes2700_doorbell *out)
{
    volatile struct bes2700_doorbell *p = (volatile struct bes2700_doorbell *)BES_DB_ADDR;

    for (uint32_t retry = 0; retry < 8; retry++) {
        if (p->magic != BES_DB_MAGIC || p->version != BES_DB_VERSION ||
            p->size != sizeof(*out)) {
            return false;
        }
        uint32_t seq = p->seq;
        if ((seq & 1) != 0) {
            continue;
        }
        __DMB();
#define BES_DB_READ(name) out->name = p->name;
        BES_DB_FIELDS(BES_DB_READ)
#undef BES_DB_READ
        __DMB();
        if (seq == p->seq) {
            return true;
        }
    }
    return false;
}

static bool doorbell_wait_count(volatile uint32_t *counter, uint32_t target)
{
    uint32_t start = hal_sys_timer_get();

    while (*counter < target) {
        if (TICKS_TO_MS(hal_sys_timer_get() - start) > 2000) {
            return false;
        }
        /* Only the real ISR updates the counter; this is not MMIO polling. */
        osSignalWait(1, 10);
    }
    return *counter == target;
}

static bool doorbell_send(void)
{
    if (!doorbell_wait_count(&doorbell_done, doorbell_sent)) {
        return false;
    }
    if (hal_sys2bth_ipc_notify_interrupt_core(HAL_SYS2BTH_ID_1) != 0) {
        return false;
    }
    doorbell_sent++;
    return true;
}

static bool doorbell_wait_stage(uint32_t stage, struct bes2700_doorbell *out)
{
    uint32_t start = hal_sys_timer_get();

    do {
        if (doorbell_snapshot(out)) {
            if (out->stage == stage) {
                return true;
            }
            if (out->stage == BES_DB_FAIL) {
                return false;
            }
        }
        osDelay(1);
    } while (TICKS_TO_MS(hal_sys_timer_get() - start) < 30000);
    return false;
}

static bool doorbell_run(struct bes2700_doorbell *s)
{
    if (!doorbell_wait_stage(BES_DB_READY, s)) {
        return false;
    }
    TRACE(3, "zephyr_db ready build=0x%08x hz=%u channel=%u !", s->build, s->hz, 1);
    TRACE(4, "zephyr_db cpu cpuid=%08x ictr=%08x ccr=%08x mpu=%08x !",
          s->cpuid, s->ictr, s->ccr, s->mpu);
    for (uint32_t i = 1; i <= BES_DB_ROUNDS; i++) {
        if (!doorbell_send() || !doorbell_wait_count(&doorbell_rx, i)) {
            return false;
        }
    }
    TRACE(1, "zephyr_db phase=bth_initiator rounds=%u pass=1 !", BES_DB_ROUNDS);
    /* Hand over explicitly; no inter-phase timing assumption. */
    if (!doorbell_send()) {
        return false;
    }
    for (uint32_t i = 1; i <= BES_DB_ROUNDS; i++) {
        if (!doorbell_wait_count(&doorbell_rx, BES_DB_ROUNDS + i) || !doorbell_send()) {
            return false;
        }
    }
    TRACE(1, "zephyr_db phase=m55_initiator rounds=%u pass=1 !", BES_DB_ROUNDS);
    if (!doorbell_wait_stage(BES_DB_RX_PAUSED, s) || !doorbell_send()) {
        return false;
    }
    osDelay(50);
    if (!doorbell_snapshot(s) || s->rx != 2 * BES_DB_ROUNDS + 1 ||
        doorbell_rx != 2 * BES_DB_ROUNDS) {
        return false;
    }
    if (!doorbell_wait_count(&doorbell_rx, 2 * BES_DB_ROUNDS + 1)) {
        return false;
    }
    TRACE(0, "zephyr_db phase=rx_pause pass=1 !");
    if (!doorbell_wait_stage(BES_DB_BURST_READY, s)) {
        return false;
    }
    NVIC_DisableIRQ(SYS2BTH_DATA1_IRQn);
    bool trigger = doorbell_send();
    osDelay(100);
    bool held = doorbell_rx == 2 * BES_DB_ROUNDS + 1;
    /* Do not clear the held pending indication. */
    NVIC_EnableIRQ(SYS2BTH_DATA1_IRQn);
    if (!trigger || !held || !doorbell_wait_count(&doorbell_rx, 2 * BES_DB_ROUNDS + 3) ||
        !doorbell_wait_count(&doorbell_done, doorbell_sent) ||
        !doorbell_wait_stage(BES_DB_PASS, s)) {
        return false;
    }
    TRACE(2, "zephyr_db phase=burst calls=%u delivered=%u pass=1 !", BES_DB_BURST, 2);
    return doorbell_sent == 2 * BES_DB_ROUNDS + 3 &&
           s->rx == doorbell_sent && s->kicks == doorbell_rx &&
           s->done == s->kicks && s->requests == 2 * BES_DB_ROUNDS + 1 + BES_DB_BURST &&
           s->queued == BES_DB_BURST - 1 && s->spurious == 0 && s->error == 0;
}

static void zephyr_m55_heartbeat_thread(void const *argument)
{
    (void)argument;
    struct bes2700_doorbell s = {};
    doorbell_thread = osThreadGetId();
    int rc = hal_sys2bth_opened(HAL_SYS2BTH_ID_1) ? -1 :
        hal_sys2bth_ipc_notify_open(HAL_SYS2BTH_ID_1, doorbell_rx_irq, doorbell_done_irq);
    if (rc == 0) {
        rc = hal_sys2bth_ipc_notify_start_recv(HAL_SYS2BTH_ID_1);
    }
#ifdef ZEPHYR_M55_DOORBELL_REPEAT
    uint32_t round = 0;
#endif
    for (;;) {
#ifdef ZEPHYR_M55_DOORBELL_REPEAT
        TRACE(3, "zephyr_db repeat round=%u ticks=%u hz=%u !",
              round, hal_sys_timer_get(), (uint32_t)CONFIG_SYSTICK_HZ);
#endif
        TRACE(0, "zephyr_db begin format=1 channel=1 rounds=1000 !");
        bool pass = rc == 0 && doorbell_run(&s);
        (void)doorbell_snapshot(&s);
#ifdef ZEPHYR_M55_DOORBELL_REPEAT
        pass = pass && s.reserved0 == round;
#endif
        TRACE(4, "zephyr_db m55 rx=%u req=%u kicks=%u done=%u !",
              s.rx, s.requests, s.kicks, s.done);
        TRACE(4, "zephyr_db state stage=%u err=%u queued=%u spurious=%u !",
              s.stage, s.error, s.queued, s.spurious);
        TRACE(3, "zephyr_db bth tx=%u rx=%u done=%u !", doorbell_sent, doorbell_rx, doorbell_done);
        TRACE(2, "zephyr_db result pass=%u rc=%d !", pass ? 1 : 0, rc);
#ifdef ZEPHYR_M55_DOORBELL_REPEAT
        TRACE(3, "zephyr_db repeat_end round=%u ticks=%u hz=%u !",
              round, hal_sys_timer_get(), (uint32_t)CONFIG_SYSTICK_HZ);
        if (pass) {
            /* The next-round notification is outside the measured round. */
            if (!doorbell_send() || !doorbell_wait_count(&doorbell_done, doorbell_sent) ||
                !doorbell_wait_stage(BES_DB_READY, &s) || s.reserved0 != round + 1) {
                TRACE(0, "zephyr_db repeat_failure !");
            } else {
                uint32_t key = int_lock();
                doorbell_rx = 0;
                doorbell_done = 0;
                doorbell_sent = 0;
                int_unlock(key);
                round++;
                continue;
            }
        }
#endif
        /* Preserve failure state and keep callback context alive. */
        for (;;) {
            osDelay(1000);
        }
    }
}

#endif
