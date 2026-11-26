// SPDX-License-Identifier: BSD-2-Clause-Patent
#ifndef LIUQIN_WCN_POWER_H
#define LIUQIN_WCN_POWER_H

#ifdef __cplusplus
extern "C" {
#endif

enum {
    LIUQIN_WCN_WLAN = 0,
    LIUQIN_WCN_BLUETOOTH = 1,
};

/* Reference-counted WCN6855 PMU power controller (RPMh rails + XO_CLK GPIO).
 * Returns 0 on success or positive errno. */
int liuqin_wcn_power_get(unsigned radio);
int liuqin_wcn_power_put(unsigned radio);
unsigned liuqin_wcn_power_owners(void);

#ifdef __cplusplus
}
#endif

#endif
