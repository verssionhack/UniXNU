// SPDX-License-Identifier: BSD-2-Clause-Patent
// Liuqin WN8030 bridge transport. Framing and power sequencing follow the
// Linux hid-nanosic driver in the user's Xiaomi Pad 6 Pro workspace.
#include "LiuqinInputBoard.h"
#include <libkern/OSKextLib.h>
#include <mach/kmod.h>
extern "C" {
#include "GeniI2c.h"
#include "Wn8030.h"
}
extern kmod_info_t g_kernel_kmod_info;
extern "C" void cover_init(void) __asm__("__GLOBAL__sub_I_KeyboardCover.cpp");
extern "C" IOService *sheng_keyboard_cover_allocate(void);
extern "C" IOService *liuqin_touch_hid_allocate(void);
namespace {
struct Keyboard {
    LqRegion gcc, se;
    LqPin reset, wake, power, irq, status, sda, scl;
    GeniI2c bus = {};
    volatile unsigned pending = 0;
    unsigned frames = 0, reports = 0, errors = 0, reads = 0, keys = 0;
    volatile unsigned irqs = 0;
};
Keyboard *kb;
IOService *hid;
IOService *touchHid;
uint32_t readBus(void *ctx, uint32_t off) {return lqRead(reinterpret_cast<uintptr_t>(ctx), off);}
void writeBus(void *ctx, uint32_t off, uint32_t value) {lqWrite(reinterpret_cast<uintptr_t>(ctx), off, value);}
void irq(void *) {
    if (kb && kb->irq.ack()) {
        __atomic_fetch_add(&kb->irqs, 1, __ATOMIC_RELAXED);
        __atomic_fetch_add(&kb->pending, 1, __ATOMIC_RELEASE);
        thread_wakeup((event_t)&kb->pending);
    }
}
bool enableBridgeRails() {
    LqRegion db, rsc;
    if (!db.map(0x80860000ULL, 0x20000) || lqRead(db.va, 4) != 0x0c0330dbu) {
        printf("LQ103 KEYBOARD PMIC cmddb unavailable\n");
        return false;
    }
    auto lookup = [&](const char *name) -> uint32_t {
        uint32_t want[2] = {0, 0};
        for (unsigned k = 0; k < 8 && name[k]; ++k)
            want[k / 4] |= uint32_t(uint8_t(name[k])) << (8u * (k % 4));
        for (unsigned i = 0; i < 8; ++i) {
            const uint32_t w0 = lqRead(db.va, 8u + i * 16u);
            const uint32_t w1 = lqRead(db.va, 12u + i * 16u);
            const unsigned slv = w0 & 0xffffu;
            if (!slv) break;
            const unsigned hdrOff = w0 >> 16, cnt = w1 >> 16;
            if ((hdrOff & 3u) || 144u + hdrOff + cnt * 24u > 0x20000u) continue;
            for (unsigned j = 0; j < cnt; ++j) {
                const unsigned e = 144u + hdrOff + j * 24u;
                if (lqRead(db.va, e) == want[0] && lqRead(db.va, e + 4u) == want[1])
                    return lqRead(db.va, e + 16u);
            }
        }
        return 0;
    };
    const uint32_t l12 = lookup("ldoc12"), l13 = lookup("ldoc13");
    if (!l12 || !l13 || !rsc.map(0x17a20000ULL, 0x10000)) {
        printf("LQ103 KEYBOARD PMIC lookup/map fail l12=0x%x l13=0x%x\n", l12, l13);
        return false;
    }
    const uint32_t rscId = lqRead(rsc.va, 0);
    const bool v3 = ((rscId >> 16) & 0xffu) >= 3u;
    const unsigned tcsId = 2u; // Active TCS 2 on apps_rsc drv-2 (sm8450.dtsi).
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
        lqWrite(rsc.va, reg, val);
        for (unsigned i = 0; i < 10000; ++i) {
            if (lqRead(rsc.va, reg) == val) return true;
            lqDelayUs(1);
        }
        return false;
    };
    uint32_t lastCst = 0, lastSt = 0;
    auto send = [&](uint32_t addr, uint32_t data) -> bool {
        for (unsigned i = 0; i < 1000; ++i) {
            if (lqRead(rsc.va, regStat) & 1u) break;
            lqDelayUs(10);
        }
        uint32_t ctrl = lqRead(rsc.va, regCtrl);
        ctrl &= ~(1u << 24);
        if (!writeSync(regCtrl, ctrl)) return false;
        ctrl &= ~(1u << 16);
        if (!writeSync(regCtrl, ctrl)) return false;
        if (!writeSync(regEn, 0)) return false;
        lqWrite(rsc.va, 0xd08u, 1u << tcsId);
        lqWrite(rsc.va, regMsg, (1u << 16) | (1u << 8) | 8u);
        lqWrite(rsc.va, regAddr, addr);
        lqWrite(rsc.va, regData, data);
        lqWrite(rsc.va, regWait, 1u);
        lqWrite(rsc.va, regEn, 1u);
        if (!writeSync(regCtrl, 1u << 16)) return false;
        lqWrite(rsc.va, regCtrl, (1u << 16) | (1u << 24));
        bool ok = false;
        for (unsigned i = 0; i < 5000; ++i) {
            lastCst = lqRead(rsc.va, regCst);
            lastSt = lqRead(rsc.va, regStat);
            if ((lastCst & (1u << 16)) && (lastSt & 1u)) { ok = true; break; }
            lqDelayUs(10);
        }
        lqWrite(rsc.va, regEn, 0);
        lqWrite(rsc.va, 0xd08u, 1u << tcsId);
        return ok;
    };
    // sm8475-xiaomi-liuqin.dts: pm8350c_l12 (1.8 V) and pm8350c_l13 (3.304 V)
    // are boot-on/always-on HPM VRM rails supplying the WN8030 bridge and I2C13.
    const struct { uint32_t addr, data; } cmds[6] = {
        {l12 + 8u, 7u}, {l12 + 0u, 1800u}, {l12 + 4u, 1u},
        {l13 + 8u, 7u}, {l13 + 0u, 3304u}, {l13 + 4u, 1u},
    };
    unsigned ok = 0;
    for (const auto &c : cmds) {
        if (!send(c.addr, c.data)) break;
        ++ok;
    }
    printf("LQ103 KEYBOARD PMIC rsc=%x l12=%x l13=%x ok=%u/6 cst=%x st=%x\n",
        rscId, l12, l13, ok, lastCst, lastSt);
    return ok == 6;
}
bool setup() {
    kb = new Keyboard;
    if (!kb || !kb->gcc.map(0x100000, 0x63000)) return false;
    const unsigned bits = (1u<<18)|(1u<<19)|(1u<<20)|(1u<<21)|(1u<<27);
    if (!lqVote(kb->gcc.va, bits)) return false;
    const unsigned halts[] = {0x3314c, 0x33140, 0x28004, 0x28008, 0x28610};
    for (unsigned off : halts) {
        unsigned tries = 0;
        while ((lqRead(kb->gcc.va, off) & (1u<<31)) && !(lqRead(kb->gcc.va, off) & 2u)) {
            if (++tries > 2000) return false;
            lqDelayUs(10);
        }
    }
    const uintptr_t rcg = kb->gcc.va + 0x28618;
    printf("LQ103 KEYBOARD CLOCK before cmd=%x cfg=%x dfs=%x cbcr=%x\n",
        lqRead(rcg,0),lqRead(rcg,4),lqRead(rcg,0x14),lqRead(kb->gcc.va,0x28610));
    if (!kb->reset.setup(83, 1u<<9) || !kb->wake.setup(42, (1u<<9)|1u) ||
        !kb->power.setup(62, 1u<<9) || !kb->irq.setup(50, 0) ||
        !kb->status.setup(46, 0) || !kb->sda.setup(48, 3u) ||
        !kb->scl.setup(49, 3u)) return false;
    // Fastboot resets can leave the bridge powered. Hold reset/pogo low,
    // enable the PM8350C LDO12 (1.8 V) and LDO13 (3.304 V) rails via RPMh,
    // then run the Linux power-on sequence.
    kb->reset.output(false); kb->wake.output(false); kb->power.output(false);
    printf("LQ103 KEYBOARD BUS pre sda=%u scl=%u\n",kb->sda.level(),kb->scl.level());
    (void)enableBridgeRails();
    lqSleep(20);
    printf("LQ103 KEYBOARD BUS off sda=%u scl=%u\n",kb->sda.level(),kb->scl.level());
    kb->power.output(true);
    lqSleep(2); kb->reset.output(true); kb->wake.output(true); lqSleep(500);
    printf("LQ103 KEYBOARD BUS on sda=%u scl=%u irq=%u\n",kb->sda.level(),kb->scl.level(),kb->irq.level());
    lqWrite(kb->sda.va,0,(lqRead(kb->sda.va,0)&~(15u<<2))|(1u<<2));
    lqWrite(kb->scl.va,0,(lqRead(kb->scl.va,0)&~(15u<<2))|(1u<<2));
    printf("LQ103 KEYBOARD PADS sda=%x/%x scl=%x/%x reset=%x wake=%x power=%x irq=%x\n",
        lqRead(kb->sda.va,0),lqRead(kb->sda.va,4),lqRead(kb->scl.va,0),lqRead(kb->scl.va,4),
        lqRead(kb->reset.va,0),lqRead(kb->wake.va,0),lqRead(kb->power.va,0),lqRead(kb->irq.va,0));
    if (!kb->se.map(0xa94000, 0x4000)) return false;
    // Match Linux geni_se_io_init: the boot loader need not leave the
    // sequencer clocks and serial outputs enabled for this unused engine.
    lqWrite(kb->se.va, 0x28, lqRead(kb->se.va, 0x28) | 0x7f);
    lqWrite(kb->se.va, 0xe30, lqRead(kb->se.va, 0xe30) | 0xf);
    lqWrite(kb->se.va, 0x24, 0x7f);
    lqWrite(kb->se.va, 0x20, 1);
    lqWrite(kb->se.va, 0xe18, 0); // FIFO completion, not GSI events.
    // Select the existing 19.2 MHz DFS level rather than assuming a level index.
    unsigned level = 8;
    for (unsigned i = 0; i < 8; ++i) {
        uintptr_t rcg = kb->gcc.va + 0x28618;
        if (lqClockHz(lqRead(rcg, 0x1c+i*4), lqRead(rcg, 0x5c+i*4), lqRead(rcg, 0x9c+i*4)) == 19200000) {level=i; break;}
    }
    if (level == 8) return false;
    lqWrite(kb->se.va, 0x7c, level);
    lqWrite(kb->se.va, GENI_CLK_CFG, (7u<<4)|1u);
    lqWrite(kb->se.va, GENI_SCL_COUNTERS, (10u<<20)|(12u<<10)|26u); // 100 kHz, Linux board default
    GeniIo io = {readBus, writeBus, reinterpret_cast<void *>(kb->se.va)};
    uint32_t config = 0;
    if (geni_i2c_prepare(&kb->bus, &io, 0x4c, &config)) {
        printf("LQ103 KEYBOARD engine rejected cfg=0x%x if=0x%x\n", config, lqRead(kb->se.va, GENI_IF_DISABLE));
        return false;
    }
    // Completion status generation requires the top-level master IRQ output.
    // The SE's SPI remains masked in GIC; only the GPIO summary IRQ is routed.
    lqWrite(kb->se.va, GENI_SE_IRQ_EN, GENI_SE_M_IRQ_EN);
    lqWrite(kb->se.va, GENI_RX_WATERMARK, kb->bus.rx_fifo_words - 1);
    lqWrite(kb->se.va, GENI_RX_RFR_WATERMARK, kb->bus.rx_fifo_words);
    printf("LQ103 KEYBOARD ENGINE cgc=%x out=%x force=%x clk=%x dfs=%x if=%x irq=%x/%x fifo=%u/%u\n",
        lqRead(kb->se.va,0x28),lqRead(kb->se.va,0x24),lqRead(kb->se.va,0x20),
        lqRead(kb->se.va,GENI_CLK_CFG),lqRead(kb->se.va,0x7c),lqRead(kb->se.va,GENI_IF_DISABLE),
        lqRead(kb->se.va,GENI_SE_IRQ_EN),lqRead(kb->se.va,GENI_M_IRQ_EN),
        kb->bus.tx_fifo_words,kb->bus.rx_fifo_words);
    if (!armcpu_spi_share || armcpu_spi_share(32+208, irq, nullptr)) return false;
    kb->irq.rising();
    return true;
}
bool readFrame(uint8_t *frame) {
    ++kb->reads;
    const uint8_t reg = 0x4c;
    if (geni_i2c_start_read_buffer(&kb->bus, &reg, 1, frame, 68)) return false;
    for (unsigned phase = 0; phase < 4; ++phase) {
        for (unsigned us = 0; us < 30000; us += 10) {
            int result = geni_i2c_poll(&kb->bus);
            if (result != GeniPending) return result == GeniDone;
            lqDelayUs(10);
        }
        if(kb->reads<=2)printf("LQ103 KEYBOARD TIMEOUT phase=%u sw=%u status=%x m=%x cmd=%x io=%x tx=%x rx=%x clk=%x cgc=%x\n",
            phase,kb->bus.phase,lqRead(kb->se.va,0x40),lqRead(kb->se.va,GENI_M_IRQ_STATUS),
            lqRead(kb->se.va,GENI_M_CMD0),lqRead(kb->se.va,0x908),
            lqRead(kb->se.va,GENI_TX_FIFO_STATUS),lqRead(kb->se.va,GENI_RX_FIFO_STATUS),
            lqRead(kb->se.va,GENI_CLK_CFG),lqRead(kb->se.va,0x28));
        if (geni_i2c_timeout(&kb->bus) == GeniFailed) break;
    }
    return false;
}
void parse(const uint8_t *frame) {
    if(kb->reads<=8)printf("LQ103 KEYBOARD RAW n=%u %02x%02x%02x%02x%02x%02x%02x%02x %02x%02x%02x%02x%02x%02x%02x%02x\n",
        kb->reads,frame[0],frame[1],frame[2],frame[3],frame[4],frame[5],frame[6],frame[7],
        frame[8],frame[9],frame[10],frame[11],frame[12],frame[13],frame[14],frame[15]);
    if (frame[0] != 0x57 || (frame[2]!=0x39 && frame[2]!=0x4a && frame[2]!=0x5b && frame[2]!=0x6c)) return;
    ++kb->frames;
    for (unsigned at = 3; at < 68 && frame[at];) {
        unsigned wire = 0, report = 0;
        switch (frame[at]) {
        case 2: wire=report=8; break;
        case 5: wire=report=9; break;
        case 6: wire=5; report=3; break;
        case 0x19: wire=report=21; break;
        case 0x22: wire=16; break;
        case 0x23: wire=32; break;
        default: return;
        }
        if (wire > 68-at) return;
        if (report) {
            if(frame[at]==5)++kb->keys;
            if (frame[at] == 6 && at + 2 < 68) {
                const uint16_t usage = uint16_t(frame[at + 1]) | (uint16_t(frame[at + 2]) << 8);
                if (usage == 0x006fu) liuqin_backlight_step(+160);
                else if (usage == 0x0070u) liuqin_backlight_step(-160);
            }
            uint8_t translated[21];
            const uint8_t *bytes = frame+at;
            if (frame[at] == 0x19) {wn8030_touchpad_report(bytes, translated); bytes=translated;}
            if (frame[at] == 2) {
                memcpy(translated,bytes,8);translated[0]=WN8030_POINTER_ID;translated[1]&=3;
                int wheel=int16_t(uint16_t(bytes[6])|(uint16_t(bytes[7])<<8));
                translated[6]=uint8_t(int8_t(wheel>127?127:wheel< -127?-127:wheel));
                translated[7]=0;bytes=translated;
            }
            sheng_keyboard_cover_input(hid, bytes, report); ++kb->reports;
        }
        at += wire;
    }
}
void worker(void *, wait_result_t) {
    if (!setup()) {printf("LQ103 KEYBOARD setup failed\n"); thread_terminate(current_thread()); return;}
    printf("LQ103 KEYBOARD ready i2c=0xa94000 irq=50 rate=100000\n");
    // The bridge may have queued its first frame before the GPIO IRQ was armed.
    __atomic_fetch_add(&kb->pending,1,__ATOMIC_RELEASE);
    unsigned ticks=0;
    for (;;) {
        uint64_t deadline; clock_interval_to_deadline(100, NSEC_PER_MSEC, &deadline);
        assert_wait_deadline((event_t)&kb->pending, THREAD_UNINT, deadline);
        if (!__atomic_load_n(&kb->pending, __ATOMIC_ACQUIRE)) thread_block(THREAD_CONTINUE_NULL);
        else clear_wait(current_thread(), THREAD_AWAKENED);
        unsigned n = __atomic_exchange_n(&kb->pending, 0, __ATOMIC_ACQ_REL);
        if (n > 32) n=32;
        while (n--) {
            uint8_t frame[68] = {};
            if (readFrame(frame)) parse(frame); else ++kb->errors;
        }
        if(++ticks%50==0)printf("LQ103 KEYBOARD STAT irq=%u reads=%u frames=%u reports=%u keys=%u errors=%u bus=%u/%x pins=%u%u%u%u%u cfg=%x vote=%x\n",
            kb->irqs,kb->reads,kb->frames,kb->reports,kb->keys,kb->errors,kb->bus.error,kb->bus.error_status,
            kb->irq.level(),kb->status.level(),kb->reset.level(),kb->wake.level(),kb->power.level(),
            lqRead(kb->irq.va,8),lqRead(kb->gcc.va,0x62008));
    }
}
}
extern "C" IOService *liuqin_input_hid(void) {return hid;}
extern "C" IOService *liuqin_touch_hid(void) {return touchHid;}
extern "C" void liuqin_input_start(void) {
    unsigned enabled=0;
    if (!PE_parse_boot_argn("liuqin-input", &enabled, sizeof(enabled)) || enabled!=1) return;
    // Vote both wrappers before either worker or the later GPU worker runs.
    // This also avoids concurrent read/modify/write by the two input workers.
    LqRegion gcc;
    if (!gcc.map(0x100000,0x63000) || !lqVote(gcc.va,
        (1u<<6)|(1u<<7)|(1u<<8)|(1u<<9)|(1u<<11)|(1u<<14)|
        (1u<<18)|(1u<<19)|(1u<<20)|(1u<<21)|(1u<<27))) return;
    if (OSKextLoadKextWithIdentifier("com.apple.iokit.IOHIDFamily") != kOSReturnSuccess) return;
    auto handle=OSMetaClass::preModLoad(g_kernel_kmod_info.name);
    if (!handle) return;
    cover_init();
    if (OSMetaClass::postModLoad(handle) != kOSReturnSuccess) return;
    auto match=IOService::serviceMatching("IOPlatformExpertDevice");
    IOService *provider=match ? IOService::copyMatchingService(match) : nullptr;
    OSSafeReleaseNULL(match);
    hid=sheng_keyboard_cover_allocate();
    if (!provider || !hid || !hid->init() || !hid->attach(provider) || !hid->start(provider)) {
        OSSafeReleaseNULL(provider); OSSafeReleaseNULL(hid); return;
    }
    touchHid=liuqin_touch_hid_allocate();
    if(!touchHid || !touchHid->init() || !touchHid->attach(provider) || !touchHid->start(provider)) {
        OSSafeReleaseNULL(touchHid);
    }
    provider->release();
    thread_t thread;
    if (kernel_thread_start(worker,nullptr,&thread)==KERN_SUCCESS) thread_deallocate(thread);
    if(touchHid)liuqin_touch_start();
    liuqin_backlight_start();
    liuqin_buttons_start();
}
