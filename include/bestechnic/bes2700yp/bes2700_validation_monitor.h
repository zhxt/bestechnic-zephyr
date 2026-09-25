/* SPDX-License-Identifier: Apache-2.0 */
/* BTH SDK implementation, included after zephyr_m55_clock_log(). */
#ifndef BES2700_VALIDATION_MONITOR_H
#define BES2700_VALIDATION_MONITOR_H
#include "bes2700_validation.h"

#ifndef ZEPHYR_M55_MONITOR_SECONDS
#define ZEPHYR_M55_MONITOR_SECONDS 600
#endif
#if ZEPHYR_M55_MONITOR_SECONDS != 0 && (ZEPHYR_M55_MONITOR_SECONDS < 10 || ZEPHYR_M55_MONITOR_SECONDS > 86400)
#error "ZEPHYR_M55_MONITOR_SECONDS must be 0 (continuous), or between 10 and 86400"
#endif

static bool zephyr_kv_snapshot(struct bes2700_validation *snapshot)
{
    volatile struct bes2700_validation *shared =
        (volatile struct bes2700_validation *)BES_KV_ADDR;
    for (unsigned int attempt = 0; attempt < 8; attempt++) {
        if (shared->magic != BES_KV_MAGIC || shared->version != BES_KV_VERSION ||
                shared->size != sizeof(*snapshot)) {
            return false;
        }
        uint32_t seq = shared->seq;
        if (seq & 1) {
            continue;
        }
        __DMB();
#define BES_KV_READ(name) snapshot->name = shared->name;
        BES_KV_FIELDS(BES_KV_READ)
#undef BES_KV_READ
        __DMB();
        if (seq == shared->seq) {
            snapshot->seq = seq;
            return true;
        }
    }
    return false;
}

static void zephyr_m55_heartbeat_thread(void const *argument)
{
    (void)argument;
    osDelay(200);
    /* Short records fit the SDK's 120-byte TRACE buffer,
     * including its prefix and CRLF. '!' detects a truncated final value.
     * Shared-memory ABI stays at version 3. */
#if ZEPHYR_M55_MONITOR_SECONDS == 0
    TRACE(0, "zephyr_kv begin continuous=1 abi=3 interval_ms=1000 format=3 !");
#else
    TRACE(2, "zephyr_kv begin seconds=%u samples=%u abi=3 interval_ms=1000 format=2 !",
        ZEPHYR_M55_MONITOR_SECONDS, ZEPHYR_M55_MONITOR_SECONDS + 1);
#endif
    for (uint32_t sample = 0; ; sample++) {
        struct bes2700_validation s;
        uint32_t bth_ticks = hal_sys_timer_get();
        uint32_t bth_ms = TICKS_TO_MS(bth_ticks);
#if ZEPHYR_M55_MONITOR_SECONDS == 0
        /* Raw unsigned ticks allow the host to unwrap timer overflow. The
         * converted bth_ms itself does not wrap modulo 2^32 milliseconds. */
        TRACE(3, "zephyr_kv clock sample=%u ticks=%u hz=%u !",
            sample, bth_ticks, (uint32_t)CONFIG_SYSTICK_HZ);
#endif
        if (!zephyr_kv_snapshot(&s)) {
            TRACE(1, "zephyr_kv invalid sample=%u !", sample);
        } else {
            TRACE(4, "zephyr_kv sample=%u bth_ms=%u build=0x%08x stage=%u !",
                sample, bth_ms, s.build_id, s.stage);
            TRACE(3, "zephyr_kv state sample=%u seq=%u publish=%u !",
                sample, s.seq, s.publish_count);
            TRACE(4, "zephyr_kv time sample=%u up=%u hz=%u cycles=%u !",
                sample, s.uptime_ms, s.configured_hz, s.raw_cycles);
            TRACE(4, "zephyr_kv fast sample=%u n=%u last=%u gap=%u !",
                sample, s.fast_count, s.fast_last_ms, s.fast_max_gap_ms);
            TRACE(4, "zephyr_kv slow sample=%u n=%u last=%u gap=%u !",
                sample, s.slow_count, s.slow_last_ms, s.slow_max_gap_ms);
            TRACE(4, "zephyr_kv queue sample=%u tx=%u rx=%u ack=%u !",
                sample, s.tx, s.rx, s.ack);
            TRACE(4, "zephyr_kv errors sample=%u full=%u err=%u to=%u !",
                sample, s.queue_full, s.seq_errors, s.ack_timeouts);
        }
        if (hal_cmu_axi_sys_get_freq() != HAL_CMU_AXI_FREQ_24M) {
            TRACE(1, "zephyr_kv clock_mismatch sample=%u !", sample);
            zephyr_m55_clock_log();
        }
#if ZEPHYR_M55_MONITOR_SECONDS != 0
        if (sample == ZEPHYR_M55_MONITOR_SECONDS) {
            break;
        }
#endif
        osDelay(1000);
    }
#if ZEPHYR_M55_MONITOR_SECONDS != 0
    TRACE(1, "zephyr_kv complete samples=%u !", ZEPHYR_M55_MONITOR_SECONDS + 1);
#endif
}
#endif
