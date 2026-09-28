/* SPDX-License-Identifier: Apache-2.0 */
#ifndef BES2700_OBSERVATION_H
#define BES2700_OBSERVATION_H
#include <stdbool.h>
#include <stdint.h>

#define BES_OBSERVATION_VERSION 1U
#define BES_OBSERVATION_SHORT_MS 60000U
#define BES_OBSERVATION_LONG_MS 600000U
#define BES_OBSERVATION_LIMIT_MS 660000U

/* Owned by one thread, or protected by the lifecycle log mutex. */
struct bes_observation {
 bool functional;
 bool short_done;
 uint32_t functional_ms;
};
static inline unsigned bes_observation_due(const struct bes_observation *o, uint32_t ms)
{
 if (!o->functional || ms < o->functional_ms ||
     ms - o->functional_ms < BES_OBSERVATION_SHORT_MS) { return 0; }
 if (!o->short_done) { return 1; }
 return ms >= BES_OBSERVATION_LONG_MS ? 2 : 0;
}
#endif
