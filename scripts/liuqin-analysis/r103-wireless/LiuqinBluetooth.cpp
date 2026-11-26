// SPDX-License-Identifier: BSD-2-Clause-Patent
// Xiaomi Pad 6 Pro (liuqin, SM8475) WCN6855 Bluetooth bring-up on QUPv3 wrap2 SE5 (uart20 @ 0x00894000).
// Exposes /dev/cu.BLTH via QcaBluetooth (qbt_tty.c) for macOS 27.3 bluetoothd + BlueTool + QcaBTType0.dylib.
// Keeps static __DATA minimal (state heap-allocated) so XNU standalone __DATA stays under 0x284000.

#include <IOKit/IOBufferMemoryDescriptor.h>
#include <IOKit/IODeviceMemory.h>
#include <IOKit/IODeviceTreeSupport.h>
#include <IOKit/IOLib.h>
#include <IOKit/IOPlatformExpert.h>
#include <IOKit/IOService.h>
#include <kern/clock.h>
#include <kern/thread.h>
#include <libkern/c++/OSData.h>
#include <libkern/libkern.h>
#include <pexpert/pexpert.h>
#include <sys/errno.h>
#include <sys/fcntl.h>
#include <sys/kauth.h>
#include <sys/param.h>
#include <sys/proc.h>
#include <sys/uio.h>
#include <sys/vnode.h>
#include <stdint.h>
#include <string.h>

#include "qbt.h"
#include "qbt_geni.h"
#include "qbt_transport.h"
#include "SmmuBypass.h"
#include "LiuqinWcnPower.h"

extern "C" {
int armcpu_spi_attach(uint32_t intid, bool edge, void (*handler)(void *), void *context,
                      uint32_t *readback, uint64_t *router);
int armcpu_spi_mask(uint32_t intid, bool masked);
extern volatile int liuqin_addon_ready;
void thread_set_thread_name(thread_t th, const char *name);
}

namespace {

// SM8475 / liuqin hardware map (verified from sm8450.dtsi, sm8475-xiaomi-liuqin.dts, gcc-sm8450.c)
constexpr uint64_t kGccBase      = 0x00100000ULL;
constexpr size_t   kGccSize      = 0x00070000u;
constexpr uint64_t kUart20Base   = 0x00894000ULL;
constexpr size_t   kUart20Size   = 0x00004000u;
constexpr uint64_t kQup2Base     = 0x008c0000ULL;
constexpr size_t   kQup2Size     = 0x00002000u;
constexpr uint64_t kTlmmBase     = 0x0f100000ULL;
constexpr size_t   kTlmmSize     = 0x00060000u; // covers gpios 0..95 (76..82)
constexpr uint64_t kAppsSmmuBase = 0x15000000ULL;
constexpr size_t   kAppsSmmuSize = 0x000d0000u;

constexpr uint32_t kUart20IntId  = 619u;   // GIC_SPI 587 + 32
constexpr uint16_t kUart20Sid    = 0x483u; // Apps SMMU SID for QUPv3 wrapper 2 / uart20

// GCC_APCS_CLOCK_BRANCH_ENA_VOTE_2 (0x62010):
//   BIT(0) wrap2_core (halt 0x33280)
//   BIT(1) wrap2_s_ahb (halt 0x2e008)
//   BIT(2) wrap2_m_ahb (halt 0x2e004)
//   BIT(3) wrap2_core_2x (halt 0x3328c)
//   BIT(9) wrap2_s5 (halt 0x2e610, RCG 0x2e618)
constexpr uint32_t kGccVote2Off  = 0x62010u;
constexpr uint32_t kWrap2CommonBits = (1u << 0) | (1u << 1) | (1u << 2) | (1u << 3);
constexpr uint32_t kWrap2S5Bit   = (1u << 9);
constexpr uint32_t kWrap2S5Halt  = 0x2e610u;
constexpr uint32_t kWrap2S5Rcg   = 0x2e618u;

// TLMM GPIOs (sm8475-xiaomi-liuqin.dts)
constexpr unsigned kCtsGpio   = 76u;
constexpr unsigned kRtsGpio   = 77u;
constexpr unsigned kTxGpio    = 78u;
constexpr unsigned kRxGpio    = 79u;
constexpr unsigned kBtEnGpio  = 81u;
constexpr unsigned kSwCtrl    = 82u;
constexpr uint32_t kBtEnCfg   = (7u << 6) | (1u << 9); // 16 mA, output, no bias
constexpr uint32_t kDmaBytes  = 32768u;
constexpr const char *kBtFwRoot = "/private/var/ngpu/firmware/qca";

struct Region {
    IOMemoryMap *map = nullptr;
    volatile uint32_t *va = nullptr;
};

struct BluetoothState {
    Region gcc, uart, wrapper, tlmm, smmu;
    IOService *radio = nullptr;
    IOBufferMemoryDescriptor *dma = nullptr;
    struct smmu_plan domain{};
    uint64_t dma_address = 0;
    struct qbt_geni geni{};
    struct qbt *core = nullptr;
    uint64_t rx_sequence = 0;
    uint32_t pending = 0;
    uint32_t power_request = 0;
    unsigned baud = 0;
    uint8_t address[6]{};
    bool resources = false;
    bool powered = false;
    bool clocked = false;
    bool serial_irq = false;
    bool service = false;
};

BluetoothState *gBt = nullptr;
uint32_t gBtStarted = 0;

inline void barrier() { __asm__ volatile("dsb sy" ::: "memory"); }

bool mapRegion(Region &r, uint64_t base, size_t bytes) {
    if (r.va) return true;
    IODeviceMemory *m = IODeviceMemory::withRange(base, bytes);
    r.map = m ? m->map(kIOMapAnywhere | kIOMapInhibitCache) : nullptr;
    if (m) m->release();
    r.va = r.map ? reinterpret_cast<volatile uint32_t *>(r.map->getVirtualAddress()) : nullptr;
    return r.va != nullptr;
}

uint64_t nowNs(void *) {
    uint64_t ns = 0;
    absolutetime_to_nanoseconds(mach_absolute_time(), &ns);
    return ns;
}

void wake(void *) {
    if (!gBt) return;
    __atomic_store_n(&gBt->pending, 1u, __ATOMIC_RELEASE);
    thread_wakeup((event_t)&gBt->pending);
}

void waitUntil(void *, uint64_t deadline) {
    if (!gBt) return;
    if (__atomic_exchange_n(&gBt->pending, 0u, __ATOMIC_ACQ_REL)) return;
    if (deadline == UINT64_MAX) {
        assert_wait((event_t)&gBt->pending, THREAD_UNINT);
    } else {
        uint64_t abs = 0;
        nanoseconds_to_absolutetime(deadline, &abs);
        assert_wait_deadline((event_t)&gBt->pending, THREAD_UNINT, abs);
    }
    if (__atomic_exchange_n(&gBt->pending, 0u, __ATOMIC_ACQ_REL))
        clear_wait(current_thread(), THREAD_AWAKENED);
    else
        thread_block(THREAD_CONTINUE_NULL);
}

uint32_t urd(void *, uint32_t reg) { return gBt->uart.va[reg / 4u]; }
void uwr(void *, uint32_t reg, uint32_t val) { gBt->uart.va[reg / 4u] = val; barrier(); }
uint32_t grd(uint32_t reg) { return gBt->gcc.va[reg / 4u]; }
void gwr(uint32_t reg, uint32_t val) { gBt->gcc.va[reg / 4u] = val; barrier(); }
uint32_t srd(void *, unsigned off) { return gBt->smmu.va[off / 4u]; }
void swr(void *, unsigned off, uint32_t val) { gBt->smmu.va[off / 4u] = val; barrier(); }

void pinCfg(unsigned gpio, uint32_t cfg, int outVal = -1) {
    volatile uint32_t *r = gBt->tlmm.va + (gpio * 0x1000u) / 4u;
    if (outVal >= 0) r[1] = outVal ? 2u : 0u;
    r[0] = cfg;
    barrier();
}

void dmaBarrier(void *) { barrier(); }

void dmaSync(void *, const struct qbt_dma_buffer *buf, size_t bytes, bool forDevice, bool tx) {
    if (bytes && (forDevice || !tx)) {
        uint64_t ctr = 0;
        __asm__ volatile("mrs %0, ctr_el0" : "=r"(ctr));
        const size_t line = size_t(4) << ((ctr >> 16) & 15u);
        uintptr_t at = reinterpret_cast<uintptr_t>(buf->bytes) & ~(line - 1);
        const uintptr_t end = reinterpret_cast<uintptr_t>(buf->bytes) + bytes;
        for (; at < end; at += line) {
            if (tx)
                __asm__ volatile("dc cvac, %0" :: "r"(at) : "memory");
            else if (forDevice)
                __asm__ volatile("dc civac, %0" :: "r"(at) : "memory");
            else
                __asm__ volatile("dc ivac, %0" :: "r"(at) : "memory");
        }
    }
    barrier();
}

void irqMask(void *, bool masked) {
    if (gBt && gBt->serial_irq) (void)armcpu_spi_mask(kUart20IntId, masked);
}

void serialIrq(void *) {
    if (gBt) qbt_geni_irq(&gBt->geni);
}

bool waitClockOn(uint32_t cbcrOff) {
    for (unsigned i = 0; i < 2000; ++i) {
        const uint32_t v = grd(cbcrOff);
        if (!(v & (1u << 31)) || (v & 2u)) return true;
        IODelay(10);
    }
    return false;
}

bool setUart20Clocks(bool enable) {
    uint32_t v = grd(kGccVote2Off);
    if (enable) {
        v |= kWrap2CommonBits | kWrap2S5Bit;
        gwr(kGccVote2Off, v);
        static const uint32_t halts[] = {0x33280u, 0x2e008u, 0x2e004u, 0x3328cu, kWrap2S5Halt};
        for (uint32_t h : halts) {
            if (!waitClockOn(h)) {
                printf("LQ103 BT clk halt timeout off=0x%x val=0x%x\n", h, grd(h));
                return false;
            }
        }
        gBt->clocked = true;
        return true;
    }
    v &= ~kWrap2S5Bit;
    gwr(kGccVote2Off, v);
    gBt->clocked = false;
    return true;
}

// Program SM8450 gcc_qupv3_wrap2_s5_clk_src (RCG @ 0x2e618) from GPLL0_OUT_EVEN (300 MHz, src=6)
int setUart20SourceRate(uint32_t baud, uint32_t *outHz) {
    uint32_t m = 0, n = 0, hz = 0;
    // All rates use src=6 (GPLL0_OUT_EVEN = 300 MHz), hid_div=1 (cfg=0), dual-edge mode=2
    switch (baud) {
    case 115200u:  m = 384u; n = 15625u; hz =  7372800u; break; // 7.3728 MHz / (16 * 4) = 115200
    case 3000000u: m =   4u; n =    25u; hz = 48000000u; break; // 48.0 MHz / 16 = 3000000
    case 3200000u: m =  64u; n =   375u; hz = 51200000u; break; // 51.2 MHz / 16 = 3200000 exact
    case 4000000u: m =  16u; n =    75u; hz = 64000000u; break; // 64.0 MHz / 16 = 4000000 exact
    default: return -EINVAL;
    }
    // Check GPLL0_OUT_EVEN is active; vote GPLL0 in APCS PLL vote (0x62000 BIT(0)) if needed
    const uint32_t rcg = kWrap2S5Rcg;
    gwr(rcg + 0x08u, m & 0xffffu);              // M
    gwr(rcg + 0x0cu, (~(n - m)) & 0xffffu);     // N (not_n_minus_m)
    gwr(rcg + 0x10u, (~n) & 0xffffu);           // D (not_2d -> 2D = N => D_reg = ~N)
    // CFG_RCGR: MODE=2 (dual-edge, bits 13:12), SRC_SEL=6 (GPLL0_OUT_EVEN, bits 10:8), SRC_DIV=0 (div 1)
    gwr(rcg + 0x04u, (2u << 12) | (6u << 8));
    // Trigger CMD_RCGR UPDATE (bit 0)
    gwr(rcg + 0x00u, grd(rcg + 0x00u) | 1u);
    for (unsigned i = 0; i < 1000; ++i) {
        if (!(grd(rcg + 0x00u) & 1u)) {
            *outHz = hz;
            return 0;
        }
        IODelay(1);
    }
    printf("LQ103 BT RCG update timeout cmd=0x%x cfg=0x%x\n", grd(rcg), grd(rcg + 4u));
    return -ETIMEDOUT;
}

size_t rxBytes(void *, const uint8_t *bytes, size_t n) {
    gBt->rx_sequence += n;
    return qbt_receive(gBt->core, bytes, n);
}

size_t nativeRx(void *, const uint8_t *bytes, size_t n) {
    return qbt_transport_receive(bytes, uint32_t(n));
}

size_t writeUart(void *, const uint8_t *p, size_t n) {
    return qbt_geni_write(&gBt->geni, p, n);
}

bool drained(void *) { return qbt_geni_drained(&gBt->geni); }
int setFlow(void *, bool enabled) { qbt_geni_set_flow(&gBt->geni, enabled); return 0; }

void pump(void *) {
    if (qbt_geni_service(&gBt->geni)) wake(nullptr);
    if (gBt->geni.state == QBT_GENI_FAILED) qbt_fail(gBt->core, gBt->geni.error);
}

int quiesce() {
    const uint64_t end = nowNs(nullptr) + 40000000ULL;
    for (;;) {
        const int e = qbt_geni_quiesce(&gBt->geni);
        if (!e) return 0;
        if (e != -EINPROGRESS && e != -EBUSY) return e;
        pump(nullptr);
        if (gBt->geni.state == QBT_GENI_STOPPED) return 0;
        if (nowNs(nullptr) >= end) return -ETIMEDOUT;
        uint64_t next = qbt_geni_deadline(&gBt->geni);
        if (next > end) next = end;
        waitUntil(nullptr, next);
    }
}

int clockVote(void *, bool enabled) {
    // Keep UART20 clock active (do not clock-gate until TLMM RX wake IRQ is verified).
    return enabled ? 0 : -EBUSY;
}

int setRate(void *, uint32_t baud) {
    int e = quiesce();
    if (e) return e;
    uint32_t hz = 0;
    e = setUart20SourceRate(baud, &hz);
    if (!e) e = qbt_geni_set_rate(&gBt->geni, baud, hz, 16u);
    if (!e) e = qbt_geni_resume(&gBt->geni);
    if (!e) gBt->baud = baud;
    printf("LQ103 BT setRate baud=%u hz=%u err=%d\n", baud, hz, e);
    return e;
}

void *btAlloc(void *, size_t n) { return IOMallocData(n); }
void btFree(void *, void *p, size_t n) { IOFreeData(p, n); }

bool validFwName(const char *name) {
    if (!name || strncmp(name, "qca/", 4) != 0) return false;
    const char *f = name + 4;
    if (!f[0] || strchr(f, '/') || strnstr(f, "..", 64)) return false;
    return (!strncmp(f, "hpbtfw", 6) || !strncmp(f, "hpnv", 4));
}

int firmwareGet(void *, const char *name, const uint8_t **data, size_t *size) {
    *data = nullptr;
    *size = 0;
    if (!validFwName(name)) {
        printf("LQ103 BT fw reject name=%s\n", name ? name : "(null)");
        return -ENOENT;
    }
    char path[160];
    snprintf(path, sizeof(path), "%s/%s", kBtFwRoot, name + 4);
    vfs_context_t ctx = vfs_context_kernel();
    vnode_t vp = NULLVP;
    int err = vnode_open(path, FREAD, 0, 0, &vp, ctx);
    uint8_t *buf = nullptr;
    size_t len = 0;
    if (!err) {
        struct vnode_attr va;
        VATTR_INIT(&va);
        VATTR_WANTED(&va, va_data_size);
        err = vnode_getattr(vp, &va, ctx);
        if (!err && (vnode_vtype(vp) != VREG || !va.va_data_size || va.va_data_size > 4u * 1024u * 1024u))
            err = EINVAL;
        if (!err) {
            len = size_t(va.va_data_size);
            buf = static_cast<uint8_t *>(IOMallocData(len));
            if (!buf) {
                err = ENOMEM;
            } else {
                int resid = 0;
                err = vn_rdwr(UIO_READ, vp, reinterpret_cast<caddr_t>(buf), int(len), 0,
                              UIO_SYSSPACE, IO_NOAUTH, vfs_context_ucred(ctx), &resid, vfs_context_proc(ctx));
                if (!err && resid) err = EIO;
            }
        }
    }
    if (vp) vnode_close(vp, FREAD, ctx);
    if (err) {
        if (buf) IOFreeData(buf, len);
        printf("LQ103 BT fw open fail path=%s err=%d\n", path, err);
        return -err;
    }
    printf("LQ103 BT fw loaded path=%s bytes=%zu\n", path, len);
    *data = buf;
    *size = len;
    return 0;
}

void firmwarePut(void *, const uint8_t *data, size_t size) {
    if (data && size) IOFreeData(const_cast<uint8_t *>(data), size);
}

void btLog(void *, int level, const char *line) {
    if (level <= 4) printf("LQ103 BT [qbt] %s\n", line);
}

bool publishAddressAndService() {
    IORegistryEntry *chosen = IORegistryEntry::fromPath("/chosen", gIODTPlane);
    if (!chosen) return false;
    // Derive deterministic locally-administered BD_ADDR from /chosen/random-seed or machine-signature
    uint64_t hash = 0xcbf29ce484222325ULL;
    bool nonzero = false;
    if (OSData *seed = OSDynamicCast(OSData, chosen->getProperty("random-seed"))) {
        const uint8_t *p = static_cast<const uint8_t *>(seed->getBytesNoCopy());
        for (unsigned i = 0; i < seed->getLength(); ++i) {
            nonzero |= (p[i] != 0);
            hash = (hash ^ p[i]) * 0x100000001b3ULL;
        }
    }
    if (!nonzero) {
        // Fallback deterministic address for liuqin (locally administered unicast)
        hash = 0x4c495551494eULL;
    }
    for (unsigned i = 0; i < 6; ++i) gBt->address[i] = uint8_t(hash >> (i * 8));
    gBt->address[0] = uint8_t((gBt->address[0] & 0xfe) | 0x02);

    IORegistryEntry *node = IORegistryEntry::fromPath("/arm-io/bluetooth", gIODTPlane);
    OSData *encoding = node ? OSDynamicCast(OSData, node->getProperty("transport-encoding")) : nullptr;
    OSData *speed = node ? OSDynamicCast(OSData, node->getProperty("transport-speed")) : nullptr;
    uint32_t wire = 0, baud = 0;
    if (encoding && encoding->getLength() == 4) memcpy(&wire, encoding->getBytesNoCopy(), 4);
    if (speed && speed->getLength() == 4) memcpy(&baud, speed->getBytesNoCopy(), 4);

    bool published = false;
    if (node && wire == 1 && baud == 3200000) {
        published = chosen->setProperty("mac-address-bluetooth0", gBt->address, 6) &&
                    node->setProperty("local-mac-address", gBt->address, 6);
        if (published && !gBt->radio) {
            IOService *radio = new IOService;
            if (radio && radio->init()) {
                radio->setName("bluetooth");
                published = radio->setProperty("device_type", "bluetooth") &&
                            radio->setProperty("transport-encoding", encoding) &&
                            radio->setProperty("transport-speed", speed) &&
                            radio->setProperty("local-mac-address", gBt->address, 6);
                IOService *provider = IOService::getPlatform();
                if (published && provider && radio->attach(provider)) {
                    gBt->radio = radio;
                    radio->registerService();
                } else {
                    published = false;
                    radio->release();
                }
            } else {
                published = false;
                if (radio) radio->release();
            }
        }
    }
    if (node) node->release();
    chosen->release();
    printf("LQ103 BT addr=%02x:%02x:%02x:%02x:%02x:%02x dt=%u wire=%u baud=%u pub=%u\n",
           gBt->address[0], gBt->address[1], gBt->address[2],
           gBt->address[3], gBt->address[4], gBt->address[5],
           node ? 1u : 0u, wire, baud, published ? 1u : 0u);
    return published;
}

int initResources() {
    if (gBt->resources) return 0;
    if (!mapRegion(gBt->gcc, kGccBase, kGccSize) ||
        !mapRegion(gBt->uart, kUart20Base, kUart20Size) ||
        !mapRegion(gBt->wrapper, kQup2Base, kQup2Size) ||
        !mapRegion(gBt->tlmm, kTlmmBase, kTlmmSize) ||
        !mapRegion(gBt->smmu, kAppsSmmuBase, kAppsSmmuSize)) {
        printf("LQ103 BT map resources fail\n");
        return -ENOMEM;
    }
    if (!publishAddressAndService()) return -ENOENT;
    const IOOptionBits opts = static_cast<IOOptionBits>(kIODirectionInOut) |
                              static_cast<IOOptionBits>(kIOMemoryPhysicallyContiguous) |
                              static_cast<IOOptionBits>(kIOMemoryMapperNone);
    if (!gBt->dma)
        gBt->dma = IOBufferMemoryDescriptor::inTaskWithOptions(kernel_task, opts, kDmaBytes, 4096);
    if (!gBt->dma) return -ENOMEM;
    IOByteCount contig = 0;
    const uint64_t pa = gBt->dma->getPhysicalSegment(0, &contig, kIOMemoryMapperNone);
    if (!pa || contig < kDmaBytes) return -EIO;

    struct smmu_io io = {nullptr, srd, swr};
    gBt->domain = smmu_plan_bypass(&io, kUart20Sid, pa, kDmaBytes);
    const char *err = gBt->domain.error ? gBt->domain.error
                                        : smmu_configure_bypass(&io, &gBt->domain, kUart20Sid);
    if (err) {
        printf("LQ103 BT SMMU bypass fail sid=0x%x slot=%u bank=%u err=%s\n",
               kUart20Sid, gBt->domain.slot, gBt->domain.bank, err);
        return -EIO;
    }
    gBt->dma_address = pa;
    printf("LQ103 BT SMMU bypass ok sid=0x%x slot=%u bank=%u pa=0x%llx\n",
           kUart20Sid, gBt->domain.slot, gBt->domain.bank, (unsigned long long)pa);
    gBt->resources = true;
    return 0;
}

int stopEngine() {
    irqMask(nullptr, true);
    uwr(nullptr, 0xe1cu, 0);
    if ((urd(nullptr, 0x40u) & 0x1001u) || (urd(nullptr, 0xe40u) & 3u)) {
        uwr(nullptr, 0x604u, 2u);
        uwr(nullptr, 0x634u, 2u);
        unsigned i = 0;
        for (; i < 1000 && (urd(nullptr, 0x40u) & 0x1001u); ++i) IODelay(1);
        if (i == 1000) return -ETIMEDOUT;
        uwr(nullptr, 0xc58u, 1u);
        uwr(nullptr, 0xd58u, 1u);
        for (i = 0; i < 1000 && (urd(nullptr, 0xe40u) & 3u); ++i) IODelay(1);
        if (i == 1000) return -ETIMEDOUT;
    }
    uwr(nullptr, 0x618u, UINT32_MAX);
    uwr(nullptr, 0x648u, UINT32_MAX);
    uwr(nullptr, 0xc44u, UINT32_MAX);
    uwr(nullptr, 0xd44u, UINT32_MAX);
    gBt->geni.state = QBT_GENI_OFF;
    gBt->geni.rx_busy = gBt->geni.tx_busy = false;
    return 0;
}

int prepareEngine() {
    uint8_t *bytes = static_cast<uint8_t *>(gBt->dma->getBytesNoCopy());
    struct qbt_dma_buffer tx = {bytes, gBt->dma_address, QBT_GENI_TX_SIZE};
    struct qbt_dma_buffer rx[QBT_GENI_RX_COUNT];
    for (unsigned i = 0; i < QBT_GENI_RX_COUNT; ++i) {
        rx[i] = {bytes + 4096u + i * QBT_GENI_RX_SIZE,
                 gBt->dma_address + 4096u + i * QBT_GENI_RX_SIZE,
                 QBT_GENI_RX_SIZE};
    }
    struct qbt_geni_ops ops = {nullptr, urd, uwr, dmaBarrier, dmaSync, nowNs, irqMask, wake, rxBytes};
    int e = qbt_geni_prepare(&gBt->geni, &ops, &tx, rx);
    if (e) return e;
    uint32_t hz = 0;
    e = setUart20SourceRate(115200u, &hz);
    if (e) return e;
    e = qbt_geni_set_rate(&gBt->geni, 115200u, hz, 16u);
    if (e) return e;
    gBt->baud = 115200u;
    return 0;
}

int powerOn() {
    if (gBt->powered) return 0;
    int e = initResources();
    if (e) return e;
    e = liuqin_wcn_power_get(LIUQIN_WCN_BLUETOOTH);
    if (e) return -e;
    gBt->powered = true;

    // Hold BT_EN low and keep UART pins in GPIO mode while controller resets
    for (unsigned gpio = kCtsGpio; gpio <= kRxGpio; ++gpio)
        pinCfg(gpio, gpio >= kTxGpio ? 3u : 1u);
    pinCfg(kSwCtrl, 1u);
    pinCfg(kBtEnGpio, kBtEnCfg, 0);
    IOSleep(100);

    if (!setUart20Clocks(true)) return -EIO;
    const uint32_t fwRev = urd(nullptr, 0x68u);
    const uint32_t wrapVer = gBt->wrapper.va[1];
    printf("LQ103 BT UART20 fw_rev=0x%x wrap_ver=0x%x vote2=0x%x\n",
           fwRev, wrapVer, grd(kGccVote2Off));
    if (wrapVer < 0x20050000u) return -ENOTSUP;
    if (((fwRev >> 8) & 0xffu) != 2u) return -ENXIO; // 2 = GENI UART protocol

    e = stopEngine();
    if (e) return e;
    e = prepareEngine();
    if (e) return e;

    if (!gBt->serial_irq) {
        uint32_t rb = 0;
        uint64_t router = 0;
        e = armcpu_spi_attach(kUart20IntId, false, serialIrq, nullptr, &rb, &router);
        if (e) {
            printf("LQ103 BT SPI attach fail intid=%u err=0x%x\n", kUart20IntId, unsigned(e));
            return -EIO;
        }
        gBt->serial_irq = true;
        irqMask(nullptr, true);
    }

    // Assert BT_EN HIGH and wait 60 ms for WCN6855 BT ROM to settle
    pinCfg(kBtEnGpio, kBtEnCfg, 1);
    IOSleep(60);

    // Switch gpio76..79 to function 1 (qup20 UART)
    for (unsigned gpio = kCtsGpio; gpio <= kRxGpio; ++gpio)
        pinCfg(gpio, (1u << 2) | (gpio >= kTxGpio ? 3u : 1u));

    e = qbt_geni_start(&gBt->geni);
    if (e) return e;

    e = qbt_boot(gBt->core, 3200000u, gBt->address);
    struct qbt_info info{};
    struct qbt_stats st{};
    qbt_get_info(gBt->core, &info);
    qbt_get_stats(gBt->core, &st);
    printf("LQ103 BT BOOT err=%d state=%u baud=%u prod=0x%x soc=0x%x rom=0x%x patch=0x%x fw=[%s] tx=%llu rx=%llu tlv=%llu/%llu wake=%llu/%llu/%llu unm=%llu to=%llu irq=%llu\n",
           e, info.state, info.baud, info.product, info.soc, info.rom, info.patch, info.firmware,
           (unsigned long long)st.tx_bytes, (unsigned long long)st.rx_bytes,
           (unsigned long long)st.tlv_sent, (unsigned long long)st.tlv_acks,
           (unsigned long long)st.wake_ind, (unsigned long long)st.wake_retries,
           (unsigned long long)st.wake_ack, (unsigned long long)st.unmatched_events,
           (unsigned long long)st.timeouts,
           (unsigned long long)gBt->geni.stats.interrupts);
    return e;
}

int powerOff() {
    if (!gBt->powered) return 0;
    qbt_set_service(gBt->core, false);
    gBt->service = false;
    int e = 0;
    if (gBt->geni.state != QBT_GENI_OFF && gBt->clocked) {
        int s = qbt_shutdown(gBt->core);
        if (!e) e = s;
        int q = quiesce();
        if (!e) e = q;
    }
    irqMask(nullptr, true);
    pinCfg(kBtEnGpio, kBtEnCfg, 0);
    IOSleep(100);
    if (gBt->clocked) {
        int st = stopEngine();
        if (!e) e = st;
        (void)setUart20Clocks(false);
    }
    gBt->powered = false;
    int rel = liuqin_wcn_power_put(LIUQIN_WCN_BLUETOOTH);
    if (!e) e = -rel;
    return e;
}

int requestPower(void *, bool enabled) {
    if (!gBt) return -ENODEV;
    __atomic_store_n(&gBt->power_request, enabled ? 1u : 2u, __ATOMIC_RELEASE);
    wake(nullptr);
    return 0;
}

void reportPowerResult(bool enabled, int err) {
    struct qbt_info info{};
    if (gBt->core) qbt_get_info(gBt->core, &info);
    qbt_transport_power_result(enabled, err ? (err < 0 ? -err : err) : 0, info.firmware, gBt->baud);
}

void btWorker(void *, wait_result_t) {
    thread_set_thread_name(current_thread(), "liuqin-bluetooth");
    struct qbt_platform ops = {
        nullptr, btAlloc, btFree, nowNs, writeUart, drained, setRate, setFlow,
        clockVote, pump, waitUntil, nativeRx, firmwareGet, firmwarePut, btLog,
    };
    gBt->core = qbt_create(&ops);
    if (!gBt->core) {
        printf("LQ103 BT qbt_create fail\n");
        return;
    }
    struct qbt_transport_ops transport = {nullptr, wake, requestPower};
    int e = qbt_transport_init(&transport);
    if (e) {
        printf("LQ103 BT qbt_transport_init fail err=%d\n", e);
        return;
    }
    // Wait for NGPUADD2 addon unpack (which writes /private/var/ngpu/firmware/qca/*)
    while (!__atomic_load_n(&liuqin_addon_ready, __ATOMIC_ACQUIRE))
        IOSleep(25);

    e = powerOn();
    if (e) (void)powerOff();
    reportPowerResult(true, e);

    uint64_t nextLog = nowNs(nullptr) + 10000000000ULL;
    uint64_t closeAt = 0;
    for (;;) {
        const uint32_t cmd = __atomic_exchange_n(&gBt->power_request, 0u, __ATOMIC_ACQ_REL);
        if (cmd) {
            e = (cmd == 1u) ? powerOn() : powerOff();
            if (e && cmd == 1u) (void)powerOff();
            reportPowerResult(cmd == 1u, e);
        }
        if (gBt->powered) {
            pump(nullptr);
            const bool active = qbt_transport_active();
            if (active != gBt->service) {
                qbt_set_service(gBt->core, active);
                gBt->service = active;
                closeAt = active ? 0 : (nowNs(nullptr) + 500000000ULL);
                printf("LQ103 BT TTY active=%u\n", active ? 1u : 0u);
            }
            uint8_t tx[2048];
            size_t room = qbt_transmit_capacity(gBt->core);
            if (room > sizeof(tx)) room = sizeof(tx);
            if (room) {
                const uint32_t n = qbt_transport_tx_take(tx, uint32_t(room));
                if (n && qbt_transmit(gBt->core, tx, n)) e = -EIO;
            }
            qbt_step(gBt->core);
            struct qbt_info info{};
            qbt_get_info(gBt->core, &info);
            if (info.state == 3 || gBt->geni.state == QBT_GENI_FAILED ||
                (closeAt && nowNs(nullptr) >= closeAt)) {
                const int ferr = (info.state == 3) ? info.error : gBt->geni.error;
                (void)powerOff();
                reportPowerResult(false, ferr);
                closeAt = 0;
            }
        }
        const uint64_t t = nowNs(nullptr);
        if (t >= nextLog) {
            struct qbt_stats st{};
            qbt_get_stats(gBt->core, &st);
            printf("LQ103 BT STAT pwr=%u svc=%u baud=%u tx=%llu rx=%llu host=%llu deliv=%llu wake=%llu/%llu/%llu irq=%llu act=%u,%u,%u,%u\n",
                   gBt->powered ? 1u : 0u, gBt->service ? 1u : 0u, gBt->baud,
                   (unsigned long long)st.tx_bytes, (unsigned long long)st.rx_bytes,
                   (unsigned long long)st.host_bytes, (unsigned long long)st.delivered_bytes,
                   (unsigned long long)st.wake_ind, (unsigned long long)st.wake_retries,
                   (unsigned long long)st.wake_ack,
                   (unsigned long long)gBt->geni.stats.interrupts,
                   qbt_transport_activity[0], qbt_transport_activity[1],
                   qbt_transport_activity[2], qbt_transport_activity[3]);
            nextLog = t + 10000000000ULL;
        }
        uint64_t deadline = gBt->powered ? qbt_deadline(gBt->core) : UINT64_MAX;
        const uint64_t gd = gBt->powered ? qbt_geni_deadline(&gBt->geni) : UINT64_MAX;
        if (gd < deadline) deadline = gd;
        if (nextLog < deadline) deadline = nextLog;
        if (closeAt && closeAt < deadline) deadline = closeAt;
        if (!deadline) {
            thread_yield_to_preemption();
            continue;
        }
        waitUntil(nullptr, deadline);
    }
}

} // namespace

extern "C" void liuqin_bluetooth_start(void) {
    uint32_t expected = 0;
    if (!__atomic_compare_exchange_n(&gBtStarted, &expected, 1u, false, __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE))
        return;
    gBt = new BluetoothState;
    if (!gBt) {
        printf("LQ103 BT oom\n");
        return;
    }
    thread_t th = nullptr;
    if (kernel_thread_start(btWorker, nullptr, &th) == KERN_SUCCESS)
        thread_deallocate(th);
    else
        printf("LQ103 BT thread start fail\n");
}
