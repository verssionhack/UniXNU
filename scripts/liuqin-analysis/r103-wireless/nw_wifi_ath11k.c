/* SPDX-License-Identifier: BSD-2-Clause-Patent */
/* Start mainline cfg80211/mac80211/mhi/qrtr and ath11k PCIe transport for WCN6855. */
#include "lx_pci.h"
#include "lx_plat.h"
#include <net/mac80211.h>
#include "core.h"
#include "debug.h"
#include "nw_mhi.h"
#include "nw_qrtr.h"
#include "nw_mainline.h"
#include "nw_wifi.h"
#include "nw_board.h"
#include "nw_events.h"
#include "nw_control_endpoint.h"
#include "pci.h"
#include <linux/mhi.h>

int ath11k_pci_init(void);
void ath11k_pci_exit(void);
int mhi_init_hook(void);
extern unsigned int ath11k_debug_mask;

struct nw_wifi_stats nw_wifi_stats;
static struct ieee80211_hw *g_hw;
void nw_wifi_hw_ready(struct ieee80211_hw *hw) { g_hw = hw; }
int lx_init_cfg80211_init(void);
int lx_init_ieee80211_init(void);
void lx_exit_cfg80211_exit(void);
void lx_exit_ieee80211_exit(void);
static bool cfg_started, mac_started, pci_started, mhi_started, qrtr_started;
extern const struct bus_type mhi_bus_type;

static int has_text(const char *s, const char *w) {
  for (; *s; s++) {
    const char *a = s, *b = w;
    while (*a && *b && *a == *b) { a++; b++; }
    if (!*b) return 1;
  }
  return 0;
}

static int g_wmi_stuck;
static void ring_state(struct ath11k_base *ab, int p) {
  struct ath11k_ce_pipe *pipe = &ab->ce.ce_pipe[p];
  if (pipe->src_ring) {
    struct hal_srng *s = &ab->hal.srng_list[pipe->src_ring->hal_ring_id];
    lx_log(3, "stuck: ce%d src sw %u write %u hp %u reap %u cached-tp %u tp %u", p,
           pipe->src_ring->sw_index, pipe->src_ring->write_index,
           s->u.src_ring.hp, s->u.src_ring.reap_hp, s->u.src_ring.cached_tp,
           s->u.src_ring.tp_addr ? *(volatile u32 *)s->u.src_ring.tp_addr : 0xffffffffu);
  }
  if (pipe->dest_ring) {
    struct hal_srng *s = &ab->hal.srng_list[pipe->dest_ring->hal_ring_id];
    lx_log(3, "stuck: ce%d buf sw %u write %u hp %u cached-tp %u tp %u needed %u", p,
           pipe->dest_ring->sw_index, pipe->dest_ring->write_index,
           s->u.src_ring.hp, s->u.src_ring.cached_tp,
           s->u.src_ring.tp_addr ? *(volatile u32 *)s->u.src_ring.tp_addr : 0xffffffffu,
           pipe->rx_buf_needed);
  }
  if (pipe->status_ring) {
    struct hal_srng *s = &ab->hal.srng_list[pipe->status_ring->hal_ring_id];
    lx_log(3, "stuck: ce%d status sw %u tp %u cached-hp %u hp %u", p,
           pipe->status_ring->sw_index, s->u.dst_ring.tp, s->u.dst_ring.cached_hp,
           s->u.dst_ring.hp_addr ? *s->u.dst_ring.hp_addr : 0xffffffffu);
  }
}

static void wmi_stuck(void) {
  if (g_wmi_stuck != 1 || !g_hw) return;
  g_wmi_stuck = 2;
  struct ath11k *ar = g_hw->priv;
  struct ath11k_base *ab = ar->ab;
  struct ath11k_pci *ab_pci = ath11k_pci_priv(ab);
  for (int p = 0; p <= 4; p++) ring_state(ab, p);
  lx_log(3, "stuck: pdev_id=%u wmi_eid=%d tot_cred=%d cf=%d flags=0x%lx",
         ar->pdev ? ar->pdev->pdev_id : 99u, ar->wmi ? ar->wmi->eid : -1,
         ab->htc.total_transmit_credits, ab->hw_params.credit_flow ? 1 : 0,
         ab->dev_flags);
  for (int e = 0; e <= 2; e++) {
    struct ath11k_htc_ep *ep = &ab->htc.endpoint[e];
    lx_log(3, "stuck: ep%d svc=0x%x ul=%u dl=%u cred=%d flow=%d seq=%u",
           e, ep->service_id, ep->ul_pipe_id, ep->dl_pipe_id,
           ep->tx_credits, ep->tx_credit_flow_enabled ? 1 : 0, ep->seq_no);
  }
  struct ath11k_ce_pipe *ce3 = &ab->ce.ce_pipe[3];
  if (ce3->src_ring && ce3->src_ring->base_addr_owner_space) {
    u32 *d = (u32 *)ce3->src_ring->base_addr_owner_space;
    for (int i = 0; i < 4; i++) {
      lx_log(3, "stuck: ce3d[%d] %08x %08x %08x %08x", i, d[i*4+0], d[i*4+1], d[i*4+2], d[i*4+3]);
    }
  }
  for (int i = 0; i < ab->qmi.mem_seg_count; i++) {
    struct target_mem_chunk *c = &ab->qmi.target_mem[i];
    lx_log(3, "stuck: qmi seg%d type=%u pa=0x%llx sz=0x%x", i, c->type, (unsigned long long)c->paddr, c->size);
  }
  lx_log(3, "stuck: ep2_cred=%d mhi ee=%d dev_st=%d pm_st=0x%x",
         ab->htc.endpoint[ATH11K_HTC_EP_2].tx_credits,
         ab_pci->mhi_ctrl->ee, ab_pci->mhi_ctrl->dev_state, ab_pci->mhi_ctrl->pm_state);
  if (nw_board && nw_board->bar) {
    const volatile u8 *m = nw_board->bar;
    u32 bhi = readl(m + 0x28);
    if (bhi >= nw_board->bar_len) bhi = 0x100;
    lx_log(3, "stuck: bar mhist=0x%x mhictl=0x%x ee=0x%x bhi_st=0x%x err=0x%x",
           readl(m + 0x48), readl(m + 0x38), readl(m + bhi + 0x28),
           readl(m + bhi + 0x2c), readl(m + bhi + 0x30));
  }
}

static void log_tap(int level, const char *line) {
  static int done;
  (void)level;
  if (!g_wmi_stuck && has_text(line, "wmi command") && has_text(line, "timeout")) g_wmi_stuck = 1;
  if (done || !has_text(line, "MHI_CB_EE_RDDM") || !nw_board || !nw_board->bar) return;
  done = 1;
  const volatile u8 *m = nw_board->bar;
  u32 bhi = readl(m + 0x28);
  if (bhi >= nw_board->bar_len) bhi = 0x100;
  lx_log(3, "rddm: mhistatus %08x mhictrl %08x ee %08x bhi-status %08x err %08x dbg %08x %08x %08x",
         readl(m + 0x48), readl(m + 0x38), readl(m + bhi + 0x28), readl(m + bhi + 0x2c),
         readl(m + bhi + 0x30), readl(m + bhi + 0x34), readl(m + bhi + 0x38), readl(m + bhi + 0x3c));
}

void nw_wifi_tx_reasons(char *b, int n) {
  if (n > 0) b[0] = 0;
}

void nw_wifi_link_state(char *text, int size) {
  struct nw_wifi_status state;
  nw_wifi_status_get(&state);
  if (size > 0) text[0] = 0;
  if (!g_hw || state.state != NW_STA_UP) return;
  snprintf(text, size, "freq %u rssi %d", state.freq_mhz, state.signal_dbm);
}

static int hexval(char c) {
  return c >= '0' && c <= '9' ? c - '0'
       : c >= 'a' && c <= 'f' ? c - 'a' + 10
       : c >= 'A' && c <= 'F' ? c - 'A' + 10 : -1;
}

void nw_board_mac(u8 *a) {
  static u8 made[6];
  static int have;
  const u8 *d;
  size_t n;
  if (!have && lx_plat->fw_get && !lx_plat->fw_get("wlan_mac.bin", &d, &n)) {
    size_t s = 0;
    for (size_t i = 0; i < n; i++) if (d[i] == '=') s = i + 1;
    u8 m[6];
    size_t k = 0;
    for (size_t i = s; i < n && k < 12; i++) {
      int v = hexval((char)d[i]);
      if (v < 0) { if (k) break; continue; }
      m[k / 2] = (u8)(k & 1 ? (m[k / 2] << 4) | v : v);
      k++;
    }
    if (k == 12 && is_valid_ether_addr(m)) {
      memcpy(made, m, 6);
      have = 1;
      lx_log(6, "wifi: address from wlan_mac.bin");
    }
  }
  if (!have) {
    for (int i = 0; i < 6; i++) made[i] = (u8)(lx_random_u32() ^ (lx_now_ms() >> (i * 3)));
    made[0] = (made[0] & 0xfe) | 0x02;
    have = 1;
    lx_log(4, "wifi: generated fallback mac");
  }
  memcpy(a, made, 6);
}

void nw_wifi_irq_mode(int delivered) { lx_irq_polling(!delivered); }
void nw_wifi_poll(void) { nw_mainline_poll(); nw_wifi_control_poll(); }
void nw_wifi_irq_pending(uint32_t vectors) {
  if (!nw_board) return;
  while (vectors) {
    unsigned bit = __builtin_ctz(vectors);
    vectors &= vectors - 1;
    lx_irq_raise(nw_board->irq_base + bit);
  }
}
unsigned nw_wifi_wait_ms(unsigned maximum) {
  return nw_mainline_pending() || nw_wifi_control_pending() ? 0 : lx_next_wait_ms(maximum);
}
void nw_wifi_set_platform(const struct lx_platform *p) { lx_plat = p; }

int nw_wifi_start(const struct lx_platform *p, const struct nw_board *b) {
  lx_plat = p;
  nw_board = b;
  ath11k_debug_mask = 0;
  nw_wifi_buffer_pool_configure(1024 * 1024);
  lx_root_init();
  lx_log_tap = log_tap;
  nw_qrtr_init();
  int r = nw_mainline_init(); if (r) goto fail;
  r = lx_init_cfg80211_init(); if (r) goto fail;
  cfg_started = true;
  r = lx_init_ieee80211_init(); if (r) goto fail;
  mac_started = true;
  r = mhi_init_hook(); if (r) goto fail;
  mhi_started = true;
  r = nw_qrtr_mhi_register(); if (r) goto fail;
  qrtr_started = true;
  nw_wifi_stats.stage = 1;
  r = ath11k_pci_init();
  if (r) goto fail;
  pci_started = true;
  nw_wifi_stats.stage = 2;
  return 0;
fail:
  nw_wifi_stats.last_err = r;
  nw_wifi_stop();
  lx_log(3, "wifi: ath11k driver start failed: %d", r);
  return r;
}

int nw_wifi_step(void) {
  static unsigned last_frames;
  nw_wifi_control_poll();
  lx_pump();
  nw_mainline_run();
  wmi_stuck();
  const unsigned f = nw_wifi_stats.frames;
  const int moved = f != last_frames;
  last_frames = f;
  return moved || nw_mainline_pending() || nw_wifi_control_pending() || lx_next_wait_ms(1000) == 0;
}

void nw_wifi_stop(void) {
  nw_mainline_shutdown();
  nw_wifi_control_shutdown();
  if (pci_started) { ath11k_pci_exit(); pci_started = false; }
  if (qrtr_started) { nw_qrtr_mhi_unregister(); qrtr_started = false; }
  if (mhi_started) { bus_unregister(&mhi_bus_type); mhi_started = false; }
  if (mac_started) { lx_exit_ieee80211_exit(); mac_started = false; }
  if (cfg_started) { lx_exit_cfg80211_exit(); cfg_started = false; }
  g_hw = NULL;
  nw_wifi_buffer_pool_configure(0);
}
