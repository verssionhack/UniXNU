// SPDX-License-Identifier: BSD-2-Clause-Patent
// Xiaomi Pad 6 Pro (liuqin, SM8475) Kinetic KTZ8866 panel backlight controller.
// Single KTZ8866 at I2C 0x11 on QUPv3 wrapper 0 SE 1 (i2c1 @ 0x00984000),
// matching sm8475-xiaomi-liuqin.dts (current-num-sinks = 5, 11-bit level 0..2047
// in BL_BRT_LSB 0x04 [2:0] and BL_BRT_MSB 0x05 [7:0]).
#include "LiuqinInputBoard.h"
extern "C" {
#include "GeniI2c.h"
}

namespace {
constexpr uint64_t kGccBase = 0x00100000ULL;
constexpr uint64_t kI2c1Base = 0x00984000ULL;
constexpr uint8_t kKtzAddr = 0x11u;
constexpr uint8_t kRegBrtLsb = 0x04u;
constexpr uint8_t kRegBrtMsb = 0x05u;
constexpr uint32_t kMaxLevel = 2047u;
constexpr uint32_t kMinVisible = 64u;

struct BacklightState {
    LqRegion gcc, se;
    GeniI2c bus = {};
    volatile uint32_t pending = 0;
    volatile int32_t target = -1;
    uint32_t current = 1024;
    uint32_t saved = 1024;
    volatile uint32_t blanked = 0;
    uint32_t writes = 0, errors = 0;
    bool ready = false;
};
BacklightState *gBl = nullptr;

uint32_t blRead(void *ctx, uint32_t off) { return lqRead(reinterpret_cast<uintptr_t>(ctx), off); }
void blWrite(void *ctx, uint32_t off, uint32_t value) { lqWrite(reinterpret_cast<uintptr_t>(ctx), off, value); }

bool waitTransfer(GeniI2c *bus) {
    for (unsigned phase = 0; phase < 4; ++phase) {
        for (unsigned us = 0; us < 25000; us += 10) {
            int res = geni_i2c_poll(bus);
            if (res != GeniPending) return res == GeniDone;
            lqDelayUs(10);
        }
        if (geni_i2c_timeout(bus) == GeniFailed) break;
    }
    return false;
}

bool readReg(uint8_t reg, uint8_t *out) {
    if (!gBl || geni_i2c_start_read(&gBl->bus, reg)) return false;
    if (!waitTransfer(&gBl->bus)) return false;
    *out = gBl->bus.data;
    return true;
}

bool writeReg(uint8_t reg, uint8_t val) {
    if (!gBl || geni_i2c_start_write(&gBl->bus, reg, val)) return false;
    return waitTransfer(&gBl->bus);
}

bool writeLevel(uint32_t level) {
    if (level > kMaxLevel) level = kMaxLevel;
    bool ok = writeReg(kRegBrtLsb, uint8_t(level & 7u)) &&
              writeReg(kRegBrtMsb, uint8_t((level >> 3) & 0xffu));
    if (ok) {
        gBl->current = level;
        ++gBl->writes;
    } else {
        ++gBl->errors;
    }
    return ok;
}

bool setup() {
    gBl = new BacklightState;
    if (!gBl || !gBl->gcc.map(kGccBase, 0x63000)) return false;
    // QUPv3 wrapper 0 m_ahb(6), s_ahb(7), core(8), core_2x(9), s1(11) voted in liuqin_input_start().
    const unsigned voteBits = (1u << 6) | (1u << 7) | (1u << 8) | (1u << 9) | (1u << 11);
    if (!lqVote(gBl->gcc.va, voteBits)) return false;
    const unsigned halts[] = {0x27004u, 0x27008u, 0x33000u, 0x3300cu, 0x27140u};
    for (unsigned off : halts) {
        if (lqRead(gBl->gcc.va, off) & 2u) continue; // HW_CTL gated AHB branch
        unsigned tries = 0;
        while (lqRead(gBl->gcc.va, off) & (1u << 31)) {
            if (++tries > 2000) return false;
            lqDelayUs(10);
        }
    }
    if (!gBl->se.map(kI2c1Base, 0x4000)) return false;
    // If UEFI left clock/timing configured, preserve it; otherwise enable 19.2 MHz DFS + 100 kHz.
    if ((lqRead(gBl->se.va, GENI_CLK_CFG) & 1u) == 0u) {
        lqWrite(gBl->se.va, 0x28, lqRead(gBl->se.va, 0x28) | 0x7fu);
        lqWrite(gBl->se.va, 0xe30, lqRead(gBl->se.va, 0xe30) | 0xfu);
        lqWrite(gBl->se.va, 0x24, 0x7fu);
        lqWrite(gBl->se.va, 0x20, 1u);
        lqWrite(gBl->se.va, 0xe18, 0u);
        const uintptr_t rcg = gBl->gcc.va + 0x27148u;
        for (unsigned i = 0; i < 8; ++i) {
            if (lqClockHz(lqRead(rcg, 0x1cu + i * 4u), lqRead(rcg, 0x5cu + i * 4u), lqRead(rcg, 0x9cu + i * 4u)) == 19200000ULL) {
                lqWrite(gBl->se.va, 0x7cu, i);
                break;
            }
        }
        lqWrite(gBl->se.va, GENI_CLK_CFG, (7u << 4) | 1u);
        lqWrite(gBl->se.va, GENI_SCL_COUNTERS, (10u << 20) | (12u << 10) | 26u);
    }
    GeniIo io = {blRead, blWrite, reinterpret_cast<void *>(gBl->se.va)};
    uint32_t cfg = 0;
    if (geni_i2c_prepare(&gBl->bus, &io, kKtzAddr, &cfg)) {
        printf("LQ103 BACKLIGHT prepare failed cfg=0x%x if=0x%x\n", cfg, lqRead(gBl->se.va, GENI_IF_DISABLE));
        return false;
    }
    lqWrite(gBl->se.va, GENI_SE_IRQ_EN, GENI_SE_M_IRQ_EN);
    uint8_t lsb = 0, msb = 0;
    bool got = readReg(kRegBrtLsb, &lsb) && readReg(kRegBrtMsb, &msb);
    if (!got) {
        printf("LQ103 BACKLIGHT probe read failed err=%u st=0x%x cfg=0x%x\n",
               gBl->bus.error, gBl->bus.error_status, cfg);
        return false;
    }
    uint32_t brt = (uint32_t(msb) << 3) | uint32_t(lsb & 7u);
    gBl->current = brt;
    gBl->saved = brt > kMinVisible ? brt : 1024u;
    gBl->target = int32_t(brt);
    gBl->ready = true;
    printf("LQ103 BACKLIGHT ready i2c=0x984000 addr=0x11 brt=%u cfg=0x%x\n", brt, cfg);
    return true;
}

void wakeWorker() {
    if (!gBl) return;
    __atomic_store_n(&gBl->pending, 1u, __ATOMIC_RELEASE);
    thread_wakeup((event_t)&gBl->pending);
}

void worker(void *, wait_result_t) {
    thread_set_thread_name(current_thread(), "liuqin-backlight");
    if (!setup()) {
        printf("LQ103 BACKLIGHT setup failed\n");
        thread_terminate(current_thread());
        return;
    }
    for (;;) {
        int32_t want = __atomic_load_n(&gBl->target, __ATOMIC_ACQUIRE);
        if (want >= 0 && uint32_t(want) != gBl->current) {
            (void)writeLevel(uint32_t(want));
            continue;
        }
        assert_wait((event_t)&gBl->pending, THREAD_UNINT);
        if (__atomic_exchange_n(&gBl->pending, 0u, __ATOMIC_ACQ_REL))
            clear_wait(current_thread(), THREAD_AWAKENED);
        else
            thread_block(THREAD_CONTINUE_NULL);
    }
}
} // namespace

extern "C" void liuqin_backlight_set_blank(bool blank) {
    if (!gBl || !gBl->ready) return;
    if (blank) {
        if (__atomic_exchange_n(&gBl->blanked, 1u, __ATOMIC_ACQ_REL) == 0u) {
            int32_t cur = __atomic_load_n(&gBl->target, __ATOMIC_ACQUIRE);
            if (cur > 0) gBl->saved = uint32_t(cur);
            __atomic_store_n(&gBl->target, 0, __ATOMIC_RELEASE);
            printf("LQ103 BACKLIGHT blank saved=%u\n", gBl->saved);
            wakeWorker();
        }
    } else {
        if (__atomic_exchange_n(&gBl->blanked, 0u, __ATOMIC_ACQ_REL) != 0u) {
            uint32_t restore = gBl->saved >= kMinVisible ? gBl->saved : 1024u;
            __atomic_store_n(&gBl->target, int32_t(restore), __ATOMIC_RELEASE);
            printf("LQ103 BACKLIGHT wake brt=%u\n", restore);
            wakeWorker();
        }
    }
}

extern "C" void liuqin_backlight_toggle_blank(void) {
    if (!gBl || !gBl->ready) return;
    liuqin_backlight_set_blank(__atomic_load_n(&gBl->blanked, __ATOMIC_ACQUIRE) == 0u);
}

extern "C" void liuqin_backlight_step(int delta) {
    if (!gBl || !gBl->ready) return;
    if (__atomic_load_n(&gBl->blanked, __ATOMIC_ACQUIRE)) {
        liuqin_backlight_set_blank(false);
        return;
    }
    int32_t cur = __atomic_load_n(&gBl->target, __ATOMIC_ACQUIRE);
    if (cur < 0) cur = int32_t(gBl->current);
    int32_t next = cur + delta;
    if (next < int32_t(kMinVisible)) next = int32_t(kMinVisible);
    if (next > int32_t(kMaxLevel)) next = int32_t(kMaxLevel);
    gBl->saved = uint32_t(next);
    __atomic_store_n(&gBl->target, next, __ATOMIC_RELEASE);
    printf("LQ103 BACKLIGHT step %d -> %d\n", delta, next);
    wakeWorker();
}

extern "C" void liuqin_backlight_start(void) {
    thread_t thread = nullptr;
    if (kernel_thread_start(worker, nullptr, &thread) == KERN_SUCCESS)
        thread_deallocate(thread);
}
