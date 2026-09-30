/* SPDX-License-Identifier: Apache-2.0 */
#ifndef BES2700YP_GPIO_VALIDATION_H
#define BES2700YP_GPIO_VALIDATION_H
#include <stdint.h>
struct bes_gpio_button {
 uint32_t candidate, stable, since, known, armed, down, presses, releases;
};
/* Initial held key is not a press. Require stable release to arm each cycle. */
static inline int bes_gpio_button_update(struct bes_gpio_button *b,uint32_t level,uint32_t ms)
{
 if(level!=b->candidate){b->candidate=level;b->since=ms;return 0;}
 if(ms-b->since<50U || (b->known && level==b->stable)){return 0;}
 b->known=1;b->stable=level;
 if(level){if(b->down){b->releases++;b->down=0;}b->armed=1;}
 else if(b->armed){b->presses++;b->down=1;b->armed=0;}
 return 1;
}
int bes_gpio_validation_init(void);
int bes_gpio_validation_poll(void);
int bes_gpio_validation_done(void);
int bes_gpio_validation_functional(void);
void bes_gpio_validation_timing(uint32_t sample,uint32_t rc);
void bes_gpio_validation_end(void);
#endif
