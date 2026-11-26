// SPDX-License-Identifier: BSD-2-Clause-Patent
// SM8475 resources from linux-sm8450-liuqin's sm8450.dtsi,
// sm8475-xiaomi-liuqin.dts, gcc-sm8450.c and pinctrl-sm8450.c.
#pragma once
#include <IOKit/IOService.h>
#include <IOKit/IOLib.h>
#include <IOKit/IODeviceMemory.h>
#include <IOKit/IOMemoryDescriptor.h>
#include <libkern/c++/OSSharedPtr.h>
#include <kern/clock.h>
#include <kern/thread.h>
#include <pexpert/pexpert.h>
#include <string.h>

struct LqRegion {
    OSSharedPtr<IOMemoryMap> keep;
    uintptr_t va = 0;
    bool map(uint64_t pa, unsigned bytes) {
        IODeviceMemory *mem = IODeviceMemory::withRange(pa, bytes);
        if (!mem) return false;
        keep = OSSharedPtr<IOMemoryMap>(mem->map(kIOMapAnywhere | kIOMapInhibitCache), OSNoRetain);
        mem->release();
        va = keep ? keep->getVirtualAddress() : 0;
        return va != 0;
    }
};
static inline uint32_t lqRead(uintptr_t va, unsigned off) {return *reinterpret_cast<volatile uint32_t *>(va + off);}
static inline void lqWrite(uintptr_t va, unsigned off, uint32_t value) {
    *reinterpret_cast<volatile uint32_t *>(va + off) = value;
    __asm__ volatile("dsb sy" ::: "memory");
}
static inline void lqDelayUs(unsigned us) {
    uint64_t hz, start, now;
    __asm__ volatile("mrs %0, cntfrq_el0" : "=r"(hz));
    __asm__ volatile("isb; mrs %0, cntpct_el0" : "=r"(start));
    const uint64_t ticks = (hz * us + 999999) / 1000000;
    do {__asm__ volatile("mrs %0, cntpct_el0" : "=r"(now));} while (now - start < ticks);
}
static inline void lqSleep(unsigned ms) {
    uint64_t deadline;
    clock_interval_to_deadline(ms, NSEC_PER_MSEC, &deadline);
    assert_wait_deadline(current_thread(), THREAD_UNINT, deadline);
    thread_block(THREAD_CONTINUE_NULL);
}
struct LqPin : LqRegion {
    bool setup(unsigned n, uint32_t ctl) {
        if (!map(0x0f100000ULL + n * 0x1000ULL, 0x1000)) return false;
        lqWrite(va, 8, lqRead(va, 8) & ~1u);
        // SM8450 eGPIO-capable pads need bit12 to select local TLMM control.
        // Match msm_pinmux_set_mux(), retaining the hardware presence bit.
        const uint32_t present = lqRead(va, 0) & (1u << 11);
        lqWrite(va, 0, ctl | present | (present ? 1u << 12 : 0));
        return true;
    }
    void output(bool on) {lqWrite(va, 4, on ? 2u : 0u);}
    bool level() const {return lqRead(va, 4) & 1;}
    void rising() {
        lqWrite(va, 12, 0);
        uint32_t cfg = lqRead(va, 8) & ~0xffu;
        lqWrite(va, 8, cfg | (3u << 5) | (1u << 4) | (1u << 2) | (1u << 1) | 1u);
    }
    bool ack() {
        if (!(lqRead(va, 12) & 1)) return false;
        lqWrite(va, 12, 0); return true;
    }
};
// Both wrappers are voted before the GPU is started. Worker calls only verify
// those votes, avoiding concurrent updates to this shared GCC register.
static inline bool lqVote(uintptr_t gcc, unsigned bits) {
    if ((lqRead(gcc, 0x62008) & bits) == bits) return true;
    lqWrite(gcc, 0x62008, lqRead(gcc, 0x62008) | bits);
    return (lqRead(gcc, 0x62008) & bits) == bits;
}
static inline uint64_t lqClockHz(uint32_t cfg, uint32_t mreg, uint32_t nreg) {
    const unsigned src = (cfg >> 8) & 7, hid = cfg & 31, mode = (cfg >> 12) & 3;
    uint64_t rate = src == 0 ? 19200000 : src == 1 ? 600000000 : src == 6 ? 300000000 : 0;
    if (hid) rate = rate * 2 / (hid + 1);
    const unsigned m = mreg & 65535, n = ((~nreg) & 65535) + m;
    if (mode) rate = n ? rate * m / n : 0;
    return rate;
}
extern "C" int armcpu_spi_share(uint32_t, void (*)(void *), void *) __attribute__((weak_import));
extern "C" IOService *liuqin_input_hid(void);
extern "C" IOService *liuqin_touch_hid(void);
extern "C" void sheng_keyboard_cover_input(IOService *, const uint8_t *, uint32_t);
extern "C" void liuqin_touch_start(void);
extern "C" void liuqin_backlight_start(void);
extern "C" void liuqin_backlight_step(int delta);
extern "C" void liuqin_backlight_set_blank(bool blank);
extern "C" void liuqin_backlight_toggle_blank(void);
extern "C" void liuqin_buttons_start(void);
