/* SPDX-License-Identifier: Apache-2.0 */
#ifndef MESSAGE_REPORT_H
#define MESSAGE_REPORT_H
#include <bes2700_message.h>
struct q_case { uint32_t id, expected, bth, m55; };
struct q_report { uint32_t finished, rc, session; struct q_state bth, m55; struct q_case cases[11]; };
void q_prepare(uint32_t build, uint32_t session);
void q_start(void);
void q_stop(void);
void q_snapshot(struct q_report *out);
#endif
