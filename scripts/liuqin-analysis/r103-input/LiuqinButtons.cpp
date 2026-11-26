// SPDX-License-Identifier: BSD-2-Clause-Patent
// Xiaomi Pad 6 Pro (liuqin, SM8475) physical buttons and folio Hall sensors:
//   - Power (PMK8350 PON PPID 0x013 bit 7): short press toggles backlight sleep/wake
//   - Volume Down (PMK8350 PON PPID 0x013 bit 6): HID Consumer Volume Decrement (0x00ea)
//   - Volume Up (PM8350 GPIO6 PPID 0x18d bit 0, active low): HID Consumer Volume Increment (0x00e9)
//   - Hall Lid (TLMM GPIO 10, active low): blanks/wakes panel backlight on lid close/open
//   - Hall Tablet Mode (TLMM GPIO 23, active high): tracked & logged
// SPMI PMIC arbiter v7 (0xc400000, EE 0, PDC pin 1 -> GIC SPI 481) matches sm8450.dtsi.
#include "LiuqinInputBoard.h"

extern "C" int armcpu_spi_attach(uint32_t, bool, void (*)(void *), void *, uint32_t *, uint64_t *) __attribute__((weak_import));

namespace {
constexpr uint64_t kSpmiCore   = 0x0c400000ULL;
constexpr uint64_t kSpmiCnfg   = 0x0c42d000ULL;
constexpr uint64_t kSpmiObsrvr = 0x0c440000ULL;
constexpr uint64_t kSpmiIntr   = 0x0c4c0000ULL;
constexpr uint64_t kSpmiChnls  = 0x0c500000ULL;
constexpr uint64_t kPdcBase    = 0x0b220000ULL;

constexpr uint32_t kPonPpid = 0x013u, kVolUpPpid = 0x18du;
constexpr uint8_t kPowerBit = 1u << 7, kResinBit = 1u << 6, kGpioBit = 1u << 0;
constexpr uint32_t kAccEnable = 0x100u, kIrqStatus = 0x104u, kIrqClear = 0x108u;
constexpr uint8_t kRtSts = 0x10u, kSetType = 0x11u, kPolHigh = 0x12u, kPolLow = 0x13u, kLatchedClr = 0x14u, kEnSet = 0x15u;
constexpr uint32_t kPdcPin = 1u, kSpi = 481u, kPdcVer = 0x1000u, kPdcCfg = 0x110u, kPdcEnBank = 0x10u;
constexpr uint32_t kBtnPower = 1u << 0, kBtnVolUp = 1u << 1, kBtnVolDown = 1u << 2;

struct ButtonsState {
    LqRegion core, cnfg, obs, chn, intr, pdc;
    LqRegion hallLid, hallTab;
    uint32_t apids = 0;
    int ponApid = -1, volUpApid = -1;
    volatile uint32_t events = 0;
    volatile uint32_t irqs = 0, otherIrqs = 0, spurious = 0;
    bool spmiOk = false;
};
ButtonsState *gBtn = nullptr;

inline volatile uint32_t *reg32(uintptr_t va, uint32_t off) {
    return reinterpret_cast<volatile uint32_t *>(va + off);
}
inline volatile uint32_t *apidReg(int apid, uint32_t reg) {
    return reg32(gBtn->chn.va, 0x1000u * uint32_t(apid) + reg);
}

int spmiWait(volatile uint32_t *ch) {
    for (unsigned n = 0; n < 100000u; ++n) {
        uint32_t s = ch[0x08 / 4];
        if (s & 1u) return (s & 0xeu) ? 2 : 0;
    }
    return 1;
}

int spmiRead8(int apid, uint8_t addr, uint8_t *out) {
    volatile uint32_t *ch = reg32(gBtn->obs.va, 0x20u * uint32_t(apid)); // EE 0
    ch[0] = (1u << 27) | (uint32_t(addr) << 4);
    int rc = spmiWait(ch);
    if (!rc) *out = uint8_t(ch[0x18 / 4]);
    return rc;
}

int spmiWrite8(int apid, uint8_t addr, uint8_t val) {
    volatile uint32_t *ch = reg32(gBtn->chn.va, 0x1000u * uint32_t(apid));
    ch[0x10 / 4] = val;
    ch[0] = (0u << 27) | (uint32_t(addr) << 4);
    return spmiWait(ch);
}

int findApid(uint32_t ppid) {
    int found = -1;
    for (uint32_t i = 0; i < gBtn->apids; ++i) {
        uint32_t m = *reg32(gBtn->core.va, 0x2000u + 4u * i);
        if (!m || ((m >> 8) & 0xfffu) != ppid) continue;
        if (((m >> 24) & 1u) && (*reg32(gBtn->cnfg.va, 4u * i) & 7u) == 0u)
            found = int(i);
    }
    return found;
}

int armPeripheral(int apid, uint8_t bits) {
    for (unsigned attempt = 0; attempt < 4; ++attempt) {
        uint8_t type = 0, hi = 0, lo = 0;
        int rc = spmiRead8(apid, kSetType, &type);
        if (!rc) rc = spmiRead8(apid, kPolHigh, &hi);
        if (!rc) rc = spmiRead8(apid, kPolLow, &lo);
        if (!rc) rc = spmiWrite8(apid, kSetType, uint8_t(type | bits));
        if (!rc) rc = spmiWrite8(apid, kPolHigh, uint8_t(hi | bits));
        if (!rc) rc = spmiWrite8(apid, kPolLow, uint8_t(lo | bits));
        if (!rc) rc = spmiWrite8(apid, kLatchedClr, bits);
        if (!rc) rc = spmiWrite8(apid, kEnSet, bits);
        if (!rc) {
            *apidReg(apid, kAccEnable) = 1u;
            __asm__ volatile("dsb sy" ::: "memory");
            return 0;
        }
        lqSleep(25);
    }
    return -1;
}

void buttonsIrq(void *) {
    if (!gBtn) return;
    bool ours = false;
    for (uint32_t w = 0; w * 32u < gBtn->apids; ++w) {
        uint32_t pend = *reg32(gBtn->intr.va, w * 4u);
        while (pend) {
            int apid = int(w * 32u + unsigned(__builtin_ctz(pend)));
            pend &= pend - 1u;
            if (apid != gBtn->ponApid && apid != gBtn->volUpApid) {
                *apidReg(apid, kIrqClear) = 0xffu;
                gBtn->otherIrqs = gBtn->otherIrqs + 1u;
                continue;
            }
            uint32_t st = *apidReg(apid, kIrqStatus);
            *apidReg(apid, kIrqClear) = st;
            if (st) (void)spmiWrite8(apid, kLatchedClr, uint8_t(st));
            ours = true;
        }
    }
    __asm__ volatile("dsb sy" ::: "memory");
    static uint32_t idle = 0;
    if (!ours) {
        gBtn->spurious = gBtn->spurious + 1u;
        if (++idle >= 1000u) {
            *reg32(gBtn->pdc.va, kPdcCfg + 4u * kPdcPin) = 4u;
            __asm__ volatile("dsb sy" ::: "memory");
        }
        return;
    }
    idle = 0;
    gBtn->irqs = gBtn->irqs + 1u;
    __atomic_fetch_add(&gBtn->events, 1u, __ATOMIC_RELEASE);
    thread_wakeup((event_t)&gBtn->events);
}

uint32_t readButtons() {
    if (!gBtn || !gBtn->spmiOk) return 0;
    uint32_t mask = 0;
    uint8_t pon = 0, gpio = 0xffu;
    if (gBtn->ponApid >= 0 && !spmiRead8(gBtn->ponApid, kRtSts, &pon)) {
        if (pon & kPowerBit) mask |= kBtnPower;
        if (pon & kResinBit) mask |= kBtnVolDown;
    }
    if (gBtn->volUpApid >= 0 && !spmiRead8(gBtn->volUpApid, kRtSts, &gpio) && !(gpio & kGpioBit))
        mask |= kBtnVolUp;
    return mask;
}

void sendConsumer(uint16_t usage) {
    IOService *hid = liuqin_input_hid();
    if (!hid) return;
    const uint8_t rep[3] = {0x06u, uint8_t(usage & 0xffu), uint8_t((usage >> 8) & 0xffu)};
    sheng_keyboard_cover_input(hid, rep, 3u);
}

bool setupSpmi() {
    if (!gBtn->core.map(kSpmiCore, 0x3000) || !gBtn->cnfg.map(kSpmiCnfg, 0x4000) ||
        !gBtn->intr.map(kSpmiIntr, 0x1000) || !gBtn->pdc.map(kPdcBase, 0x2000))
        return false;
    uint32_t ver = *reg32(gBtn->core.va, 0);
    gBtn->apids = *reg32(gBtn->core.va, 0x04) & 0x7ffu;
    if (ver < 0x70000000u || ver >= 0x80000000u || !gBtn->apids || gBtn->apids > 1024u) {
        printf("LQ103 BUTTONS unsupported spmi ver=0x%x apids=%u\n", ver, gBtn->apids);
        return false;
    }
    uint64_t obsLen = (uint64_t(0x20u) * gBtn->apids + 0xfffULL) & ~0xfffULL;
    uint64_t chnLen = uint64_t(0x1000u) * gBtn->apids;
    if (!gBtn->obs.map(kSpmiObsrvr, unsigned(obsLen)) || !gBtn->chn.map(kSpmiChnls, unsigned(chnLen)))
        return false;
    gBtn->ponApid = findApid(kPonPpid);
    gBtn->volUpApid = findApid(kVolUpPpid);
    if (gBtn->ponApid < 0) {
        printf("LQ103 BUTTONS no PON apid ver=0x%x apids=%u\n", ver, gBtn->apids);
        return false;
    }
    if (armPeripheral(gBtn->ponApid, kPowerBit | kResinBit)) return false;
    if (gBtn->volUpApid >= 0 && armPeripheral(gBtn->volUpApid, kGpioBit)) return false;

    uint32_t pdcVer = *reg32(gBtn->pdc.va, kPdcVer);
    if (pdcVer >= 0x30200u) {
        *reg32(gBtn->pdc.va, kPdcCfg + 4u * kPdcPin) = (1u << 3) | 4u;
    } else {
        *reg32(gBtn->pdc.va, kPdcCfg + 4u * kPdcPin) = 4u;
        *reg32(gBtn->pdc.va, kPdcEnBank + 4u * (kPdcPin / 32u)) |= 1u << (kPdcPin % 32u);
    }
    __asm__ volatile("dsb sy" ::: "memory");

    int rc = kIOReturnUnsupported;
    if (armcpu_spi_attach) {
        for (unsigned tries = 0; tries < 80; ++tries) {
            rc = armcpu_spi_attach(32u + kSpi, false, buttonsIrq, nullptr, nullptr, nullptr);
            if (rc != kIOReturnNotReady) break;
            lqSleep(250);
        }
    }
    gBtn->spmiOk = (rc == 0);
    printf("LQ103 BUTTONS spmi=%u ver=0x%x apids=%u pon=%d volup=%d pdc=0x%x irq_rc=0x%x\n",
           gBtn->spmiOk ? 1u : 0u, ver, gBtn->apids, gBtn->ponApid, gBtn->volUpApid, pdcVer, unsigned(rc));
    return gBtn->spmiOk;
}

void worker(void *, wait_result_t) {
    thread_set_thread_name(current_thread(), "liuqin-buttons");
    gBtn = new ButtonsState;
    if (!gBtn) { thread_terminate(current_thread()); return; }
    bool lidMapped = gBtn->hallLid.map(0x0f100000ULL + 10ULL * 0x1000ULL, 0x1000);
    bool tabMapped = gBtn->hallTab.map(0x0f100000ULL + 23ULL * 0x1000ULL, 0x1000);
    (void)setupSpmi();
    bool lidOpenSeen = lidMapped ? ((lqRead(gBtn->hallLid.va, 4) & 1u) != 0u) : false;
    bool lidClosed = lidMapped ? !lidOpenSeen : false;
    bool tabMode = tabMapped ? ((lqRead(gBtn->hallTab.va, 4) & 1u) != 0u) : false;
    printf("LQ103 BUTTONS ready spmi=%u hall_lid=%u(open=%u) hall_tab=%u(tab=%u)\n",
           gBtn->spmiOk ? 1u : 0u, lidMapped ? 1u : 0u, lidOpenSeen ? 1u : 0u,
           tabMapped ? 1u : 0u, tabMode ? 1u : 0u);

    uint32_t seen = __atomic_load_n(&gBtn->events, __ATOMIC_ACQUIRE);
    uint32_t lastMask = 0;
    uint64_t pwrDownNs = 0;
    uint8_t lidPending = 0;

    for (;;) {
        uint32_t mask = readButtons();
        if (mask != lastMask) {
            uint32_t diff = mask ^ lastMask;
            if (diff & kBtnVolUp) {
                sendConsumer((mask & kBtnVolUp) ? 0x00e9u : 0x0000u);
            }
            if (diff & kBtnVolDown) {
                sendConsumer((mask & kBtnVolDown) ? 0x00eau : 0x0000u);
            }
            if (diff & kBtnPower) {
                uint64_t nowNs = 0;
                absolutetime_to_nanoseconds(mach_absolute_time(), &nowNs);
                if (mask & kBtnPower) {
                    pwrDownNs = nowNs;
                } else if (pwrDownNs && (nowNs - pwrDownNs) < 1500000000ULL) {
                    liuqin_backlight_toggle_blank();
                }
            }
            printf("LQ103 BUTTONS mask=0x%x->0x%x\n", lastMask, mask);
            lastMask = mask;
        }
        if (lidMapped) {
            bool curClosed = (lqRead(gBtn->hallLid.va, 4) & 1u) == 0u;
            if (!curClosed) lidOpenSeen = true;
            if (curClosed != lidClosed) {
                if (++lidPending >= 2u) {
                    lidPending = 0;
                    lidClosed = curClosed;
                    printf("LQ103 HALL lid=%s\n", lidClosed ? "closed" : "open");
                    if (lidOpenSeen) liuqin_backlight_set_blank(lidClosed);
                }
            } else {
                lidPending = 0;
            }
        }
        if (tabMapped) {
            bool curTab = (lqRead(gBtn->hallTab.va, 4) & 1u) != 0u;
            if (curTab != tabMode) {
                tabMode = curTab;
                printf("LQ103 HALL tablet=%u\n", tabMode ? 1u : 0u);
            }
        }
        uint64_t deadline;
        clock_interval_to_deadline(150, NSEC_PER_MSEC, &deadline);
        assert_wait_deadline((event_t)&gBtn->events, THREAD_UNINT, deadline);
        uint32_t cur = __atomic_load_n(&gBtn->events, __ATOMIC_ACQUIRE);
        if (cur != seen) clear_wait(current_thread(), THREAD_AWAKENED);
        else thread_block(THREAD_CONTINUE_NULL);
        seen = __atomic_load_n(&gBtn->events, __ATOMIC_ACQUIRE);
    }
}
} // namespace

extern "C" void liuqin_buttons_start(void) {
    thread_t thread = nullptr;
    if (kernel_thread_start(worker, nullptr, &thread) == KERN_SUCCESS)
        thread_deallocate(thread);
}
