// SPDX-License-Identifier: BSD-2-Clause-Patent
// macOS 27.3 Wi-Fi network bridge for Xiaomi Pad 6 Pro (liuqin, WCN6855):
// binds en0 (LiuqinIdentityEthernet) to Ath11k/mac80211/cfg80211 (nw_abi.h).
#include <IOKit/IOLib.h>
#include <IOKit/IOPlatformExpert.h>
#include <kern/locks.h>
#include <kern/thread.h>
#include <kern/thread_call.h>
#include <net/ethernet.h>
#include <net/if.h>
#include <net/if_ether.h>
#include <net/kpi_interface.h>
#include <netinet/in.h>
#include <pexpert/pexpert.h>
#include <stdarg.h>
#include <sys/kern_event.h>
#include <sys/kpi_mbuf.h>
#include <sys/systm.h>
#include "nw_abi.h"
#include "nw_control_endpoint.h"

extern "C" bool sheng_ethernet_wifi_attach(int (*output)(mbuf_t));
extern "C" void sheng_ethernet_wifi_link(bool up);
extern "C" ifnet_t sheng_ethernet_ifnet(void);
extern "C" void native_wifi_logf(int level, const char *fmt, ...);
extern "C" int sheng_wifi_file(const char *name, const uint8_t **data, size_t *size);
extern "C" void sheng_wifi_wake(void);

namespace {

ifnet_t gIf;
uint8_t gMac[6];
lck_grp_t *gGrp;
lck_mtx_t *gLock;
uint32_t gRxFrames, gRxErrors;
int gRxLastError;
uint32_t gRxNoBuffer, gRxChains, gRxLongest;
mbuf_t gRxHead, gRxTail, gRxSpare;
uint32_t gRxBulkAllocations, gRxAllocRetries;
uint32_t gRxPendingPackets, gRxPendingBytes, gRxBatches, gRxLargestBatch;

void log(int level, const char *fmt, ...) __attribute__((format(printf, 2, 3)));
void log(int level, const char *fmt, ...) {
    char line[160];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(line, sizeof line, fmt, ap);
    va_end(ap);
    native_wifi_logf(level, "%s", line);
}

void on_scan_done() {
    const int n = nw_wifi_bss_count();
    log(6, "wifi-net: scan done (%d APs)", n);
    nw_bss_info b;
    for (int i = 0; i < n && i < 8; ++i) {
        if (!nw_wifi_bss_get(i, &b)) {
            log(6, "wifi-net: ap[%d] %u MHz %d dBm %02x:%02x:%02x:%02x:%02x:%02x '%.*s'",
                i, b.freq_mhz, b.signal_dbm,
                b.bssid[0], b.bssid[1], b.bssid[2], b.bssid[3], b.bssid[4], b.bssid[5],
                b.ssid_len, reinterpret_cast<const char *>(b.ssid));
        }
    }
}

void on_connect_done(int result) {
    nw_wifi_status st;
    nw_wifi_status_get(&st);
    const bool ok = (result == NW_RES_OK && st.state == NW_STA_UP);
    log(6, "wifi-net: connect done result=%d state=%u freq=%u rssi=%d", result, st.state, st.freq_mhz, st.signal_dbm);
    sheng_ethernet_wifi_link(ok);
}

void on_link_lost(int reason) {
    log(6, "wifi-net: link lost reason=%d", reason);
    sheng_ethernet_wifi_link(false);
}

void on_link_update(const nw_wifi_status *) {}

void release_rx_spares() {
    while (gRxSpare) {
        mbuf_t packet = gRxSpare;
        gRxSpare = mbuf_nextpkt(packet);
        mbuf_setnextpkt(packet, nullptr);
        mbuf_freem(packet);
    }
}

void flush_rx() {
    release_rx_spares();
    if (!gRxHead || !gIf) return;
    mbuf_t packets = gRxHead;
    const uint32_t count = gRxPendingPackets, bytes = gRxPendingBytes;
    gRxHead = gRxTail = nullptr;
    gRxPendingPackets = gRxPendingBytes = 0;
    struct ifnet_stat_increment_param inc {};
    inc.packets_in = count;
    inc.bytes_in = bytes;
    const errno_t error = ifnet_input(gIf, packets, &inc);
    gRxBatches++;
    if (count > gRxLargestBatch) gRxLargestBatch = count;
    if (error) { gRxErrors += count; gRxLastError = error; }
    else gRxFrames += count;
}

mbuf_t allocate_rx(size_t length) {
    if (length <= 2048) {
        if (!gRxSpare) {
            unsigned chunks = 1;
            if (!mbuf_allocpacket_list(16, MBUF_DONTWAIT, 2048, &chunks, &gRxSpare)) gRxBulkAllocations++;
        }
        if (gRxSpare) {
            mbuf_t packet = gRxSpare;
            gRxSpare = mbuf_nextpkt(packet);
            mbuf_setnextpkt(packet, nullptr);
            return packet;
        }
    }
    mbuf_t packet = nullptr;
    if (mbuf_allocpacket(MBUF_DONTWAIT, length, nullptr, &packet)) return nullptr;
    return packet;
}

void on_rx_packet(void *context, size_t length, nw_packet_reader reader) {
    if (!gIf) gIf = sheng_ethernet_ifnet();
    if (!gIf || length < 14) return;
    enum : size_t { Align = 2 };
    mbuf_t m = allocate_rx(length + Align);
    if (!m && gRxHead) {
        flush_rx();
        gRxAllocRetries++;
        m = allocate_rx(length + Align);
    }
    if (!m) { gRxNoBuffer++; return; }
    if (length > gRxLongest) gRxLongest = static_cast<uint32_t>(length);
    if (mbuf_next(m)) gRxChains++;
    size_t done = 0;
    bool first = true;
    for (mbuf_t n = m; n; n = mbuf_next(n)) {
        size_t room = mbuf_maxlen(n) - mbuf_leadingspace(n);
        if (first) {
            if (room < Align + 14) break;
            mbuf_setdata(n, static_cast<uint8_t *>(mbuf_datastart(n)) + mbuf_leadingspace(n) + Align, 0);
            room -= Align;
        }
        const size_t take = length - done < room ? length - done : room;
        if (reader(context, done, mbuf_data(n), take)) { done = 0; break; }
        mbuf_setlen(n, take);
        done += take;
        first = false;
    }
    if (done != length) { gRxNoBuffer++; mbuf_freem(m); return; }
    mbuf_pkthdr_setlen(m, length);
    mbuf_pkthdr_setrcvif(m, gIf);
    mbuf_pkthdr_setheader(m, mbuf_data(m));
    mbuf_adj(m, 14);
    mbuf_setnextpkt(m, nullptr);
    if (gRxTail) mbuf_setnextpkt(gRxTail, m); else gRxHead = m;
    gRxTail = m;
    gRxPendingPackets++;
    gRxPendingBytes += static_cast<uint32_t>(length);
    if (gRxPendingPackets >= 64) flush_rx();
}

int flat_read(void *context, size_t offset, void *destination, size_t length) {
    memcpy(destination, static_cast<uint8_t *>(context) + offset, length);
    return 0;
}

void on_rx(const uint8_t *eth, size_t length) {
    on_rx_packet(const_cast<uint8_t *>(eth), length, flat_read);
}

const struct nw_wifi_events gEvents = {
    on_scan_done, on_connect_done, on_link_lost, on_rx, flush_rx, on_rx_packet, on_link_update
};

int mbuf_read(void *context, size_t offset, void *destination, size_t length) {
    return mbuf_copydata(static_cast<mbuf_t>(context), offset, length, destination);
}

void mbuf_release(void *context) {
    mbuf_freem(static_cast<mbuf_t>(context));
}

int ethernet_output(mbuf_t m) {
    size_t length = mbuf_pkthdr_len(m);
    if (length >= 14 && length <= 2000) {
        if (!nw_wifi_tx_packet(m, length, mbuf_read, mbuf_release)) {
            if (gIf) ifnet_stat_increment_out(gIf, 1, static_cast<uint32_t>(length), 0);
            sheng_wifi_wake();
            return 0;
        }
    }
    mbuf_freem(m);
    return 0;
}

void trafficLog(void *, wait_result_t) {
    thread_set_thread_name(current_thread(), "liuqin-wifi-net");
    bool attached = false;
    for (unsigned waited = 0; !(attached = sheng_ethernet_wifi_attach(ethernet_output)) && waited < 30000; waited += 100) {
        IOSleep(100);
    }
    if (!attached) {
        log(3, "wifi-net: LiuqinIdentityEthernet not ready after 30s");
        return;
    }
    gIf = sheng_ethernet_ifnet();
    nw_wifi_set_events(&gEvents);
    log(6, "wifi-net: attached to en0 mac=%02x:%02x:%02x:%02x:%02x:%02x ifnet=%s",
        gMac[0], gMac[1], gMac[2], gMac[3], gMac[4], gMac[5], gIf ? "ready" : "pending");
    bool initialScan = false;
    for (unsigned second = 1;; ++second) {
        IOSleep(1000);
        if (!gIf) gIf = sheng_ethernet_ifnet();
        nw_control_stats cs {};
        nw_wifi_control_stats_get(&cs);
        if (!initialScan && cs.active_session != 0) {
            initialScan = true;
            IOSleep(1000);
            int rc = nw_wifi_scan(nullptr, 0);
            sheng_wifi_wake();
            log(6, "wifi-net: initial scan triggered (session=%llu rc=%d)",
                static_cast<unsigned long long>(cs.active_session), rc);
        }
        nw_wifi_status st;
        nw_wifi_status_get(&st);
        if (st.state == NW_STA_UP && second % 15 == 0 && gIf) {
            char ip[32] = "none";
            ifaddr_t *list = nullptr;
            if (!ifnet_get_address_list_family(gIf, &list, AF_INET) && list) {
                if (list[0]) {
                    struct sockaddr_in a {};
                    if (!ifaddr_address(list[0], reinterpret_cast<struct sockaddr *>(&a), sizeof a)) {
                        const uint8_t *b = reinterpret_cast<const uint8_t *>(&a.sin_addr);
                        snprintf(ip, sizeof ip, "%u.%u.%u.%u", b[0], b[1], b[2], b[3]);
                    }
                }
                ifnet_free_address_list(list);
            }
            struct ifnet_stats_param stats {};
            ifnet_stat(gIf, &stats);
            log(6, "wifi-net: en0 ip=%s rx=%llu tx=%llu rssi=%d freq=%u",
                ip, static_cast<unsigned long long>(stats.packets_in),
                static_cast<unsigned long long>(stats.packets_out),
                st.signal_dbm, st.freq_mhz);
        }
    }
}

} // namespace

extern "C" void sheng_wifi_net_start(const uint8_t mac[6]) {
    if (gGrp) return;
    memcpy(gMac, mac, 6);
    gGrp = lck_grp_alloc_init("wifi-net", LCK_GRP_ATTR_NULL);
    gLock = lck_mtx_alloc_init(gGrp, LCK_ATTR_NULL);
    thread_t t = nullptr;
    if (kernel_thread_start(trafficLog, nullptr, &t) == KERN_SUCCESS) thread_deallocate(t);
}
