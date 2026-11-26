// SPDX-License-Identifier: BSD-2-Clause-Patent
// Shared WCN6855 PMU power controller for Xiaomi Pad 6 Pro (liuqin, SM8475).
// Drives RPMh VRM rails via APPS RSC DRV2 TCS 2 (cmd-db @ 0x80860000, RSC @ 0x17a20000)
// and asserts WCN6855 XO_CLK GPIO (tlmm 204) per sm8475-xiaomi-liuqin.dts & pwrseq-qcom-wcn.c.

#include "LiuqinWcnPower.h"

#include <IOKit/IODeviceMemory.h>
#include <IOKit/IOLib.h>
#include <IOKit/IOLocks.h>
#include <libkern/libkern.h>
#include <sys/errno.h>
#include <stdint.h>
#include <string.h>

namespace {

constexpr uint64_t kCmdDbBase = 0x80860000ULL;
constexpr size_t kCmdDbSize = 0x20000u;
constexpr uint64_t kRscDrvBase = 0x17a20000ULL;
constexpr size_t kRscDrvSize = 0x10000u;
constexpr uint64_t kTlmmBase = 0x0f100000ULL;
constexpr unsigned kXoClkGpio = 204u;

struct MmioMap {
    IOMemoryMap *map = nullptr;
    uintptr_t va = 0;
    bool open(uint64_t phys, size_t bytes) {
        IODeviceMemory *m = IODeviceMemory::withRange(phys, bytes);
        if (!m) return false;
        map = m->map(kIOMapAnywhere | kIOMapInhibitCache);
        m->release();
        if (!map) return false;
        va = map->getVirtualAddress();
        return va != 0;
    }
    ~MmioMap() {
        if (map) { map->release(); map = nullptr; va = 0; }
    }
};

inline uint32_t rd32(uintptr_t base, unsigned off) {
    return *reinterpret_cast<volatile uint32_t *>(base + off);
}
inline void wr32(uintptr_t base, unsigned off, uint32_t val) {
    *reinterpret_cast<volatile uint32_t *>(base + off) = val;
    __asm__ volatile("dsb sy" ::: "memory");
}

struct WcnRail {
    const char *name;
    uint32_t mv;
    bool keep_on; // always-on shared rail: never disable on put
};

// sm8475-xiaomi-liuqin.dts wcn6855-pmu supplies:
//   pm8350_s10 (smpb10): 1.8V vddio
//   pmr735a_s2 (smpe2):  0.95V vddaon, vddpmumx (always-on)
//   pm8350_s11 (smpb11): 0.95V vddpmu, vddpmucx, vddrfa0p95
//   pm8350_s12 (smpb12): 1.35V vddrfa1p3, vddpcie1p3
//   pm8350c_s1 (smpc1):  1.90V vddrfa1p9, vddpcie1p9 (always-on)
constexpr WcnRail kSharedRails[] = {
    {"smpb10", 1800u, false},
    {"smpe2",   950u, true},
    {"smpb11",  950u, false},
    {"smpb12", 1350u, false},
    {"smpc1",  1900u, true},
};

// pcie0_phy supplies: pm8350_l5 (ldob5, 0.88V vdda-phy) + pm8350c_l10 (ldoc10, 1.20V vdda-pll)
constexpr WcnRail kPciePhyRails[] = {
    {"ldob5",   880u, true},  // shared with UFS/camera PHY
    {"ldoc10", 1200u, true},  // shared with UFS/USB3 PHY
};

uint32_t cmdDbLookup(uintptr_t dbVa, const char *name) {
    uint32_t want[2] = {0, 0};
    for (unsigned k = 0; k < 8 && name[k]; ++k)
        want[k / 4] |= uint32_t(uint8_t(name[k])) << (8u * (k % 4));
    for (unsigned i = 0; i < 8; ++i) {
        const uint32_t w0 = rd32(dbVa, 8u + i * 16u);
        const uint32_t w1 = rd32(dbVa, 12u + i * 16u);
        const unsigned slv = w0 & 0xffffu;
        if (!slv) break;
        const unsigned hdrOff = w0 >> 16, cnt = w1 >> 16;
        if ((hdrOff & 3u) || 144u + hdrOff + cnt * 24u > kCmdDbSize) continue;
        for (unsigned j = 0; j < cnt; ++j) {
            const unsigned e = 144u + hdrOff + j * 24u;
            if (rd32(dbVa, e) == want[0] && rd32(dbVa, e + 4u) == want[1])
                return rd32(dbVa, e + 16u);
        }
    }
    return 0;
}

bool voteRails(bool shared, bool pciePhy, bool enable) {
    if (!shared && !(pciePhy && enable)) return true;
    MmioMap db, rsc;
    if (!db.open(kCmdDbBase, kCmdDbSize) || !rsc.open(kRscDrvBase, kRscDrvSize)) {
        printf("LQ103 WCN_PWR map fail\n");
        return false;
    }
    const uint32_t rscId = rd32(rsc.va, 0);
    const bool v3 = ((rscId >> 16) & 0xffu) >= 3u;
    const unsigned tcsId = 2u; // Active TCS 2 on apps_rsc drv-2 (sm8450.dtsi)
    const unsigned tcs = 0xd00u + tcsId * 672u;
    const unsigned regWait = tcs + (v3 ? 0x20u : 0x10u);
    const unsigned regCtrl = tcs + (v3 ? 0x24u : 0x14u);
    const unsigned regStat = tcs + (v3 ? 0x28u : 0x18u);
    const unsigned regEn   = tcs + (v3 ? 0x2cu : 0x1cu);
    const unsigned regMsg  = tcs + (v3 ? 0x34u : 0x30u);
    const unsigned regAddr = tcs + (v3 ? 0x38u : 0x34u);
    const unsigned regData = tcs + (v3 ? 0x3cu : 0x38u);
    const unsigned regCst  = tcs + (v3 ? 0x40u : 0x3cu);

    auto writeSync = [&](unsigned reg, uint32_t val) {
        wr32(rsc.va, reg, val);
        for (unsigned i = 0; i < 10000; ++i) {
            if (rd32(rsc.va, reg) == val) return true;
            IODelay(1);
        }
        return false;
    };

    auto send = [&](uint32_t addr, uint32_t data) -> bool {
        for (unsigned i = 0; i < 1000; ++i) {
            if (rd32(rsc.va, regStat) & 1u) break;
            IODelay(10);
        }
        uint32_t ctrl = rd32(rsc.va, regCtrl);
        ctrl &= ~(1u << 24);
        if (!writeSync(regCtrl, ctrl)) return false;
        ctrl &= ~(1u << 16);
        if (!writeSync(regCtrl, ctrl)) return false;
        if (!writeSync(regEn, 0)) return false;
        wr32(rsc.va, 0xd08u, 1u << tcsId);
        wr32(rsc.va, regMsg, (1u << 16) | (1u << 8) | 8u);
        wr32(rsc.va, regAddr, addr);
        wr32(rsc.va, regData, data);
        wr32(rsc.va, regWait, 1u);
        wr32(rsc.va, regEn, 1u);
        if (!writeSync(regCtrl, 1u << 16)) return false;
        wr32(rsc.va, regCtrl, (1u << 16) | (1u << 24));
        bool ok = false;
        for (unsigned i = 0; i < 5000; ++i) {
            if ((rd32(rsc.va, regCst) & (1u << 16)) && (rd32(rsc.va, regStat) & 1u)) {
                ok = true;
                break;
            }
            IODelay(10);
        }
        wr32(rsc.va, regEn, 0);
        wr32(rsc.va, 0xd08u, 1u << tcsId);
        return ok;
    };

    unsigned found = 0, voted = 0;
    auto doList = [&](const WcnRail *list, size_t n) -> bool {
        for (size_t idx = 0; idx < n; ++idx) {
            const size_t i = enable ? idx : (n - 1 - idx);
            const uint32_t addr = cmdDbLookup(db.va, list[i].name);
            if (!addr) {
                printf("LQ103 WCN_PWR missing rail %s\n", list[i].name);
                continue;
            }
            ++found;
            if (!enable) {
                if (!list[i].keep_on && send(addr + 4u, 0u)) ++voted;
                continue;
            }
            if (send(addr + 8u, 7u) && send(addr + 0u, list[i].mv) && send(addr + 4u, 1u))
                ++voted;
            else
                return false;
        }
        return true;
    };

    bool ok = true;
    if (shared) ok = doList(kSharedRails, sizeof(kSharedRails) / sizeof(kSharedRails[0])) && ok;
    if (pciePhy && enable) {
        ok = doList(kPciePhyRails, sizeof(kPciePhyRails) / sizeof(kPciePhyRails[0])) && ok;
        const uint32_t sn7 = cmdDbLookup(db.va, "SN7");
        if (sn7) {
            // Vote PCIe NoC BCM (SN7) active for endpoint DMA (pcie-mem path)
            if (send(sn7, (1u << 30) | (1u << 29) | (0x400u << 14) | 0x400u)) ++voted;
            ++found;
        }
        const uint32_t sh1 = cmdDbLookup(db.va, "SH1");
        if (sh1) {
            // Vote GEM NoC PCIe BCM (SH1, enable_mask=0x1 -> vote_x=0, vote_y=1)
            if (send(sh1, (1u << 30) | (1u << 29) | 1u)) ++voted;
            ++found;
        }
    }
    printf("LQ103 WCN_PWR shared=%u pcie=%u en=%u rsc=0x%x found=%u voted=%u ok=%u\n",
           shared ? 1u : 0u, pciePhy ? 1u : 0u, enable ? 1u : 0u, rscId, found, voted, ok ? 1u : 0u);
    return ok && found > 0;
}

void setXoClkGpio(bool high) {
    MmioMap gpio;
    if (!gpio.open(kTlmmBase + uint64_t(kXoClkGpio) * 0x1000ULL, 0x1000u)) return;
    // tlmm 204: GPIO func 0, 16 mA drive (7 << 6), output enable (1 << 9), pull-down when low
    const uint32_t cfg = (7u << 6) | (1u << 9) | (high ? 0u : 1u);
    wr32(gpio.va, 4u, high ? 2u : 0u);
    wr32(gpio.va, 0u, cfg);
}

IOLock *gWcnLock = nullptr;
unsigned gWcnOwners = 0;

IOLock *wcnLock() {
    IOLock *l = __atomic_load_n(&gWcnLock, __ATOMIC_ACQUIRE);
    if (l) return l;
    IOLock *cand = IOLockAlloc();
    if (!cand) return nullptr;
    if (!__atomic_compare_exchange_n(&gWcnLock, &l, cand, false, __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE)) {
        IOLockFree(cand);
        return l;
    }
    return cand;
}

} // namespace

extern "C" int liuqin_wcn_power_get(unsigned radio) {
    if (radio > LIUQIN_WCN_BLUETOOTH) return EINVAL;
    IOLock *lock = wcnLock();
    if (!lock) return ENOMEM;
    IOLockLock(lock);
    const unsigned bit = 1u << radio;
    if (gWcnOwners & bit) {
        IOLockUnlock(lock);
        return 0;
    }
    const bool first = (gWcnOwners == 0);
    const bool wantPcie = (radio == LIUQIN_WCN_WLAN);
    int err = 0;
    if (!voteRails(first, wantPcie, true)) {
        err = EIO;
    } else if (first) {
        // pwrseq-qcom-wcn.c: msleep(1), assert xo_clk_gpio HIGH, usleep(100..200), pwup_delay_ms=50
        IOSleep(1);
        setXoClkGpio(true);
        IODelay(200);
        IOSleep(50);
    }
    if (!err) {
        gWcnOwners |= bit;
    } else if (first) {
        setXoClkGpio(false);
        (void)voteRails(true, false, false);
    }
    IOLockUnlock(lock);
    return err;
}

extern "C" int liuqin_wcn_power_put(unsigned radio) {
    if (radio > LIUQIN_WCN_BLUETOOTH) return EINVAL;
    IOLock *lock = wcnLock();
    if (!lock) return ENOMEM;
    IOLockLock(lock);
    const unsigned bit = 1u << radio;
    int err = 0;
    if ((gWcnOwners & bit) && !(gWcnOwners & ~bit)) {
        setXoClkGpio(false);
        if (!voteRails(true, false, false)) err = EIO;
    }
    if (!err) gWcnOwners &= ~bit;
    IOLockUnlock(lock);
    return err;
}

extern "C" unsigned liuqin_wcn_power_owners(void) {
    IOLock *lock = wcnLock();
    if (!lock) return 0;
    IOLockLock(lock);
    const unsigned o = gWcnOwners;
    IOLockUnlock(lock);
    return o;
}
