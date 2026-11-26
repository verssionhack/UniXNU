// SPDX-License-Identifier: BSD-2-Clause-Patent
// SM8475 PCIe0 RC + QMP Gen3x1 PHY + WCN6855 (17cb:1103) full Wi-Fi bring-up for Xiaomi Pad 6 Pro (liuqin).
// Powers WCN6855 PMU + PCIe0 PHY supplies + SN7 NoC BCM, brings up PCIE_0_GDSC, GCC clocks,
// SM8475 QMP V6 Gen3x1 PHY, PARF (ops_1_9_0), BDF->SID hash (0x100 -> Apps SMMU SID 0x1c01),
// PERST# + LTSSM Gen3 x1 L0, BAR0 enumeration, Apps SMMU Stage-1 32-bit 128 MiB DMA window,
// DesignWare iMSI receiver (SPI 141), kern_ctl (org.unixnu.wifi.control), and ath11k + mac80211 + WifiNet.

#include "LiuqinWcnPower.h"
#include "LiuqinWifiPcieTables.h"
#include "nw_abi.h"
#include "nw_control_endpoint.h"

#include <IOKit/IOBufferMemoryDescriptor.h>
#include <IOKit/IODeviceMemory.h>
#include <IOKit/IODeviceTreeSupport.h>
#include <IOKit/IOLib.h>
#include <IOKit/IOLocks.h>
#include <IOKit/IOMemoryDescriptor.h>
#include <kern/clock.h>
#include <kern/cpu_data.h>
#include <kern/task.h>
#include <kern/thread.h>
#include <libkern/c++/OSData.h>
#include <libkern/libkern.h>
#include <stdarg.h>
#include <stdint.h>
#include <sys/errno.h>
#include <sys/kern_control.h>
#include <sys/kern_control_private.h>
#include <sys/kpi_mbuf.h>

extern "C" int armcpu_spi_attach(uint32_t intid, bool edge, void (*fn)(void *), void *ctx,
                                 uint32_t *rb, uint64_t *router) __attribute__((weak_import));
extern "C" int liuqin_wifi_firmware_read(const char *name, uint8_t **data, size_t *size);
extern "C" void sheng_wifi_net_start(const uint8_t mac[6]);

namespace {

constexpr uint64_t kGccBase  = 0x00100000ULL;
constexpr uint64_t kTlmmBase = 0x0f100000ULL;
constexpr uint64_t kSmmuBase = 0x15000000ULL;
constexpr uint64_t kParfBase = 0x01c00000ULL;
constexpr uint64_t kPhyBase  = 0x01c06000ULL;
constexpr uint64_t kDbiBase  = 0x60000000ULL;
constexpr uint64_t kAtuBase  = 0x60001000ULL;
constexpr uint64_t kCfgBase  = 0x60100000ULL;
constexpr uint64_t kMemBase  = 0x60300000ULL;
constexpr uint64_t kMemSize  = 0x03d00000ULL;

// gcc-sm8450.c PCIe0 registers
constexpr uint32_t kVote0 = 0x62000u;
constexpr uint32_t kVote8 = 0x62008u;
constexpr uint32_t kPcieBcr = 0x7b000u;
constexpr uint32_t kGdsc = 0x7b004u;
constexpr uint32_t kRchngRcg = 0x7b048u;
constexpr uint32_t kPipeMux = 0x7b060u;
constexpr uint32_t kAuxRcg = 0x7b064u;
constexpr uint32_t kPhyBcr = 0x7c01cu;
constexpr uint32_t kClkrefEn = 0x9c004u;

constexpr uint32_t kVote8Bits = 0x3fu;
constexpr uint32_t kVote0Bits = (1u << 11) | (1u << 12) | (1u << 19) | (1u << 20) | (1u << 22);
constexpr uint32_t kCheckBranches[] = {
    0x7b020u, 0x7b028u, 0x7b030u, 0x7b034u, 0x7b01cu, 0x7b044u, 0x7b08cu,
};
constexpr uint32_t kPipeHalt = 0x7b03cu;

constexpr unsigned kWlanEnGpio = 80u;
constexpr unsigned kPerstGpio  = 94u;
constexpr unsigned kClkReqGpio = 95u;
constexpr unsigned kWakeGpio   = 96u;

constexpr uint32_t kParfSysCtrl = 0x00u;
constexpr uint32_t kParfPmCtrl = 0x20u;
constexpr uint32_t kParfPhyCtrl = 0x40u;
constexpr uint32_t kParfMhiClkReset = 0x174u;
constexpr uint32_t kParfAxiHaltV2 = 0x1a8u;
constexpr uint32_t kParfLtssm = 0x1b0u;
constexpr uint32_t kParfDbiBaseV2 = 0x350u;
constexpr uint32_t kParfDbiBaseV2Hi = 0x354u;
constexpr uint32_t kParfSlvSpaceV2 = 0x358u;
constexpr uint32_t kParfSlvSpaceV2Hi = 0x35cu;
constexpr uint32_t kParfAtuBase = 0x634u;
constexpr uint32_t kParfAtuBaseHi = 0x638u;
constexpr uint32_t kParfDeviceType = 0x1000u;
constexpr uint32_t kParfBdfToSidTable = 0x2000u;
constexpr uint32_t kParfBdfToSidCfg = 0x2c00u;
constexpr uint32_t kSlvSpaceSz = 0x80000000u;

constexpr uint32_t kDbiCommand = 0x04u;
constexpr uint32_t kDbiBusNumbers = 0x18u;
constexpr uint32_t kDbiMemBaseLimit = 0x20u;
constexpr uint32_t kDbiLinkCtrlSta = 0x80u;
constexpr uint32_t kDbiPortDebug0 = 0x728u;
constexpr uint32_t kDbiPortDebug1 = 0x72cu;
constexpr uint32_t kDbiMsiAddrLo = 0x820u;
constexpr uint32_t kDbiMsiAddrHi = 0x824u;
constexpr uint32_t kDbiMsiEnable0 = 0x828u;
constexpr uint32_t kDbiMsiMask0 = 0x82cu;
constexpr uint32_t kDbiMsiStatus0 = 0x830u;
constexpr uint32_t kMsiSpi = 141u;

constexpr uint32_t kWifiSmmuSid = 0x1c01u;
constexpr uint64_t kDmaIovaBase = 0x20000000ULL;
constexpr size_t   kDmaWindowBytes = 128u << 20; // 128 MiB (32768 x 4 KiB pages)
constexpr unsigned kDmaL3Pages = unsigned(kDmaWindowBytes / (2u << 20)); // 64 L3 tables
constexpr unsigned kPtPages = 2u + kDmaL3Pages; // 1 L1 + 1 L2 + 64 L3 = 66 pages

struct Window {
    IOMemoryMap *map = nullptr;
    volatile uint32_t *va = nullptr;
    bool open(uint64_t base, uint64_t size) {
        IODeviceMemory *m = IODeviceMemory::withRange(base, size);
        map = m ? m->map(kIOMapAnywhere | kIOMapInhibitCache) : nullptr;
        if (m) m->release();
        va = map ? reinterpret_cast<volatile uint32_t *>(map->getVirtualAddress()) : nullptr;
        return va != nullptr;
    }
    void close() {
        if (map) { map->release(); map = nullptr; va = nullptr; }
    }
    ~Window() { close(); }
};

inline void dsb() { __asm__ volatile("dsb sy" ::: "memory"); }

void cleanRange(void *va, size_t bytes) {
    if (!bytes) return;
    uintptr_t start = reinterpret_cast<uintptr_t>(va) & ~uintptr_t(63u);
    uintptr_t end = (reinterpret_cast<uintptr_t>(va) + bytes + 63u) & ~uintptr_t(63u);
    for (uintptr_t p = start; p < end; p += 64u) {
        __asm__ volatile("dc civac, %0" :: "r"(p) : "memory");
    }
    dsb();
}

void setPin(volatile uint32_t *tlmm, unsigned pin, uint32_t cfg, int level) {
    if (level >= 0) tlmm[(pin * 0x1000u + 4u) / 4u] = level ? 2u : 0u;
    tlmm[(pin * 0x1000u) / 4u] = cfg;
    if (level >= 0) tlmm[(pin * 0x1000u + 4u) / 4u] = level ? 2u : 0u;
    dsb();
}

void pulseReset(volatile uint32_t *gcc, uint32_t bcr) {
    gcc[bcr / 4u] |= 1u;
    dsb();
    IODelay(2000);
    gcc[bcr / 4u] &= ~1u;
    dsb();
    IODelay(2000);
}

bool waitClear(volatile uint32_t *reg, uint32_t mask, unsigned tries, unsigned *used = nullptr) {
    unsigned i = 0;
    for (; i < tries && (*reg & mask); ++i) IODelay(100);
    if (used) *used = i;
    return !(*reg & mask);
}

uint8_t crc8Bdf(uint16_t bdf) {
    uint8_t crc = 0;
    const uint8_t bytes[2] = {uint8_t(bdf >> 8), uint8_t(bdf & 0xffu)};
    for (uint8_t b : bytes) {
        crc ^= b;
        for (int bit = 0; bit < 8; ++bit)
            crc = (crc & 0x80u) ? uint8_t((crc << 1) ^ 7u) : uint8_t(crc << 1);
    }
    return crc;
}

// ---- Apps SMMU Stage-1 32-bit DMA window + power-of-2 Arena ----
constexpr unsigned kArenaBlocks = 32768u;
struct Arena {
    IOBufferMemoryDescriptor *dmaDesc = nullptr;
    IOMemoryMap *dmaMap = nullptr;
    IOBufferMemoryDescriptor *ptDesc = nullptr;
    IOMemoryMap *ptMap = nullptr;
    uint8_t *va = nullptr;
    uint64_t iova = 0;
    size_t bytes = 0;
    struct Block { uint32_t off, size; bool used; } *blocks = nullptr;
    unsigned count = 0;
    size_t used = 0, peak = 0;
    unsigned failures = 0;
    uint32_t smmuBank = 0, smmuSlot = 0;
} gArena;

bool setupSmmuDmaWindow(uint32_t sid) {
    Window smmu;
    if (!smmu.open(kSmmuBase, 0x100000u)) {
        printf("LQ103 WIFI_SMMU map fail\n");
        return false;
    }
    volatile uint32_t *s = smmu.va;
    const uint32_t idr0 = s[0x20u / 4u];
    const uint32_t idr1 = s[0x24u / 4u];
    const uint32_t idr2 = s[0x28u / 4u];
    const uint32_t numSmr = idr0 & 0xffu;
    const uint32_t numBanks = idr1 & 0xffu;
    const uint32_t pageSz = (idr1 >> 31) ? 0x10000u : 0x1000u;
    const uint32_t numPages = 1u << (((idr1 >> 28) & 7u) + 1u);
    const uint32_t paCode = (idr2 >> 4) & 0xfu;
    if (!numSmr || numBanks < 2u || (numPages + numBanks) * pageSz > 0x100000u) {
        printf("LQ103 WIFI_SMMU bad geom idr0=0x%x idr1=0x%x idr2=0x%x\n", idr0, idr1, idr2);
        return false;
    }

    // Find free SMR slot (or reuse existing SID slot)
    int slot = -1;
    for (uint32_t i = 0; i < numSmr && i < 128u; ++i) {
        const uint32_t smr = s[(0x800u + 4u * i) / 4u];
        if ((smr & (1u << 31)) && (smr & 0x7fffu) == sid) { slot = int(i); break; }
    }
    if (slot < 0) {
        for (uint32_t i = 0; i < numSmr && i < 128u; ++i) {
            if (!(s[(0x800u + 4u * i) / 4u] & (1u << 31))) { slot = int(i); break; }
        }
    }
    if (slot < 0) {
        printf("LQ103 WIFI_SMMU no free SMR\n");
        return false;
    }

    // Find free context bank (skip bank 0 and numBanks - 1 shared bypass bank; require virgin CBAR/CBA2R/SCTLR/FSR)
    int bank = -1;
    for (int b = int(numBanks) - 2; b >= 1; --b) {
        bool inUse = false;
        for (uint32_t i = 0; i < numSmr && i < 128u; ++i) {
            const uint32_t smr = s[(0x800u + 4u * i) / 4u];
            if (!(smr & (1u << 31))) continue;
            const uint32_t s2cr = s[(0xc00u + 4u * i) / 4u];
            if (((s2cr >> 16) & 3u) == 0u && (s2cr & 0xffu) == uint32_t(b)) { inUse = true; break; }
        }
        if (inUse) continue;
        if (s[(0x1000u + 4u * uint32_t(b)) / 4u] != 0u) continue;
        if (s[(0x1800u + 4u * uint32_t(b)) / 4u] != 0u) continue;
        const uint32_t cbOff = (numPages + uint32_t(b)) * pageSz;
        if ((s[cbOff / 4u] & 1u) != 0u) continue;
        if ((s[(cbOff + 0x58u) / 4u] & 0xc00001feu) != 0u) continue;
        bank = b;
        break;
    }
    if (bank < 0) {
        printf("LQ103 WIFI_SMMU no free bank\n");
        return false;
    }

    // Allocate 128 MiB DMA buffer (4 KiB pages, cached kernel VA — sm8475 pcie0 is dma-coherent) + 66 page-table pages
    gArena.dmaDesc = IOBufferMemoryDescriptor::withOptions(kIODirectionInOut, kDmaWindowBytes, 4096);
    if (!gArena.dmaDesc || gArena.dmaDesc->prepare(kIODirectionInOut) != kIOReturnSuccess) {
        printf("LQ103 WIFI_SMMU dma alloc fail\n");
        return false;
    }
    gArena.va = static_cast<uint8_t *>(gArena.dmaDesc->getBytesNoCopy());
    if (!gArena.va) {
        printf("LQ103 WIFI_SMMU dma va fail\n");
        return false;
    }
    gArena.iova = kDmaIovaBase;
    gArena.bytes = kDmaWindowBytes;
    bzero(gArena.va, gArena.bytes);
    cleanRange(gArena.va, gArena.bytes);

    gArena.ptDesc = IOBufferMemoryDescriptor::withOptions(kIODirectionInOut, kPtPages * 4096u, 4096);
    if (!gArena.ptDesc || gArena.ptDesc->prepare(kIODirectionInOut) != kIOReturnSuccess) {
        printf("LQ103 WIFI_SMMU pt alloc fail\n");
        return false;
    }
    uint64_t *ptVa = static_cast<uint64_t *>(gArena.ptDesc->getBytesNoCopy());
    if (!ptVa) {
        printf("LQ103 WIFI_SMMU pt va fail\n");
        return false;
    }
    bzero(ptVa, kPtPages * 4096u);

    uint64_t ptPa[kPtPages] = {};
    for (unsigned i = 0; i < kPtPages; ++i) {
        IOByteCount segLen = 0;
        ptPa[i] = gArena.ptDesc->getPhysicalSegment(i * 4096u, &segLen, kIOMemoryMapperNone);
        if (!ptPa[i] || segLen < 4096u) {
            printf("LQ103 WIFI_SMMU pt phys fail idx=%u\n", i);
            return false;
        }
    }

    // L1[0] -> L2 (covers 0x00000000..0x3fffffff)
    ptVa[0] = ptPa[1] | 3ULL;
    // L2[256..287] -> L3[0..31] (covers 0x20000000..0x23ffffff)
    const unsigned l2Base = unsigned(kDmaIovaBase >> 21);
    for (unsigned m = 0; m < kDmaL3Pages; ++m) {
        ptVa[512u + l2Base + m] = ptPa[2u + m] | 3ULL;
    }
    // L3 leaf entries: Normal Write-Back R/W Alloc (MAIR idx 1 = 0xff, matching sm8475 pcie0 dma-coherent + Sm8550QupDma.c),
    // Inner Shareable (3), AP[1]=1 (unprivileged RW), AF=1, nG=1, UXN|PXN
    constexpr uint64_t kLeafAttr = (1ULL << 11) | (1ULL << 10) | (3ULL << 53) | (3ULL << 8) | (1ULL << 6) | (1ULL << 2) | 3ULL;
    uint64_t page0Pa = 0;
    for (unsigned m = 0; m < kDmaL3Pages; ++m) {
        uint64_t *l3 = ptVa + (2u + m) * 512u;
        for (unsigned k = 0; k < 512u; ++k) {
            const uint64_t off = (uint64_t(m) * 512u + k) * 4096ULL;
            IOByteCount segLen = 0;
            const uint64_t pa = gArena.dmaDesc->getPhysicalSegment(off, &segLen, kIOMemoryMapperNone);
            if (!pa || segLen < 4096u) {
                printf("LQ103 WIFI_SMMU dma phys fail off=0x%llx\n", (unsigned long long)off);
                return false;
            }
            if (m == 0 && k == 0) page0Pa = pa;
            l3[k] = pa | kLeafAttr;
        }
    }
    cleanRange(ptVa, kPtPages * 4096u);

    // Program context bank (matching Sm8550QupDma.c verified Qualcomm Apps SMMU sequence)
    const uint32_t cbOff = (numPages + uint32_t(bank)) * pageSz;
    volatile uint32_t *cb = s + (cbOff / 4u);
    const uint32_t asid = uint32_t(bank) & 0xffu;
    const uint64_t ttbr0 = (uint64_t(asid) << 48) | ptPa[0];

    cb[0x00u / 4u] = 0u;
    dsb();
    s[(0x1800u + 4u * uint32_t(bank)) / 4u] = 1u;       // CBA2R: AArch64
    s[(0x1000u + 4u * uint32_t(bank)) / 4u] = 0x1f300u; // CBAR: S1 trans, S2 bypass
    dsb();
    cb[0x10u / 4u] = paCode | (7u << 15);               // TCR2: SEP=7, PASize=paCode
    cb[0x30u / 4u] = 32u | (1u << 8) | (1u << 10) | (3u << 12) | (1u << 23); // TCR: T0SZ=32, IRGN0=WB, ORGN0=WB, SH0=Inner, EPD1=1, TG0=4K
    cb[0x20u / 4u] = uint32_t(ttbr0);
    cb[0x24u / 4u] = uint32_t(ttbr0 >> 32);
    cb[0x28u / 4u] = 0u;
    cb[0x2cu / 4u] = 0u;
    cb[0x38u / 4u] = 0xff44u; // MAIR0: idx0=0x44 NC, idx1=0xff WB
    cb[0x3cu / 4u] = 0u;
    cb[0x58u / 4u] = 0xffffffffu; // clear FSR
    dsb();
    cb[0x618u / 4u] = 0u; // TLBIALL
    cb[0x7f0u / 4u] = 0u; // TLBSYNC
    for (unsigned i = 0; i < 1000 && (cb[0x7f4u / 4u] & 1u); ++i) IODelay(1);
    cb[0x00u / 4u] = 0x00c01027u; // SCTLR: HUPCF|CFCFG=0|CFRE|TRE|AFE|M (+ ASIDPNE)
    dsb();

    const uint32_t rbSctlr = cb[0x00u / 4u];
    const uint64_t rbTtbr0 = uint64_t(cb[0x20u / 4u]) | (uint64_t(cb[0x24u / 4u]) << 32);
    if ((rbSctlr & 0x27u) != 0x27u || rbTtbr0 != ttbr0) {
        printf("LQ103 WIFI_SMMU cb readback fail bank=%d sctlr=0x%x ttbr0=0x%llx exp=0x%llx\n",
               bank, rbSctlr, (unsigned long long)rbTtbr0, (unsigned long long)ttbr0);
        return false;
    }

    // Bind SID 0x1c01 -> bank (S2CR before SMR per Qualcomm firmware quirk)
    s[(0xc00u + 4u * uint32_t(slot)) / 4u] = uint32_t(bank);
    dsb();
    s[(0x800u + 4u * uint32_t(slot)) / 4u] = (1u << 31) | (sid & 0x7fffu);
    dsb();
    const uint32_t rbS2cr = s[(0xc00u + 4u * uint32_t(slot)) / 4u];
    const uint32_t rbSmr  = s[(0x800u + 4u * uint32_t(slot)) / 4u];
    if (rbS2cr != uint32_t(bank) || rbSmr != ((1u << 31) | (sid & 0x7fffu))) {
        printf("LQ103 WIFI_SMMU stream readback fail s2cr=0x%x smr=0x%x\n", rbS2cr, rbSmr);
        return false;
    }

    gArena.blocks = static_cast<Arena::Block *>(IOMallocData(kArenaBlocks * sizeof(Arena::Block)));
    if (!gArena.blocks) return false;
    gArena.blocks[0] = {4096u, uint32_t(gArena.bytes - 4096u), false}; // page 0 reserved as MSI target
    gArena.count = 1u;
    gArena.used = gArena.peak = 4096u;
    gArena.failures = 0u;
    gArena.smmuBank = uint32_t(bank);
    gArena.smmuSlot = uint32_t(slot);

    printf("LQ103 WIFI_SMMU ok bank=%d slot=%d asid=%u iova=0x%llx sz=0x%zx pa0=0x%llx ttbr0=0x%llx sctlr=0x%x fsr=0x%x\n",
           bank, slot, asid, (unsigned long long)kDmaIovaBase, kDmaWindowBytes,
           (unsigned long long)page0Pa, (unsigned long long)rbTtbr0, rbSctlr, cb[0x58u / 4u]);
    return true;
}

void *arenaAlloc(size_t n, uint64_t *bus) {
    n = (n + 63u) & ~size_t(63u);
    if (n >= 4096u) n = (n + 4095u) & ~size_t(4095u);
    uint32_t align = 64u;
    if (n >= 4096u) { align = 4096u; while (align < n) align <<= 1; }
    for (unsigned i = 0; i < gArena.count; ++i) {
        Arena::Block &b = gArena.blocks[i];
        if (b.used) continue;
        const uint32_t start = (b.off + align - 1u) & ~(align - 1u), pad = start - b.off;
        if (b.size < pad + n) continue;
        const bool tail = b.size > pad + n;
        const unsigned extra = (pad ? 1u : 0u) + (tail ? 1u : 0u);
        if (gArena.count + extra > kArenaBlocks) continue;
        const Arena::Block whole = b;
        memmove(&gArena.blocks[i + extra], &gArena.blocks[i], (gArena.count - i) * sizeof(Arena::Block));
        gArena.count += extra;
        unsigned at = i;
        if (pad) { gArena.blocks[at] = {whole.off, pad, false}; ++at; }
        gArena.blocks[at] = {start, uint32_t(n), true};
        if (tail) gArena.blocks[at + 1] = {start + uint32_t(n), whole.size - pad - uint32_t(n), false};
        uint8_t *p = gArena.va + start;
        gArena.used += n;
        if (gArena.used > gArena.peak) gArena.peak = gArena.used;
        bzero(p, n);
        if (bus) *bus = gArena.iova + start;
        return p;
    }
    ++gArena.failures;
    printf("LQ103 WIFI_DMA full want=%zu used=%zu/%zu blocks=%u\n", n, gArena.used, gArena.bytes, gArena.count);
    return nullptr;
}

void arenaFree(void *p) {
    if (!p || static_cast<uint8_t *>(p) < gArena.va || static_cast<uint8_t *>(p) >= gArena.va + gArena.bytes) return;
    const uint32_t off = uint32_t(static_cast<uint8_t *>(p) - gArena.va);
    for (unsigned i = 0; i < gArena.count; ++i) {
        if (gArena.blocks[i].off != off || !gArena.blocks[i].used) continue;
        gArena.used -= gArena.blocks[i].size;
        gArena.blocks[i].used = false;
        if (i + 1 < gArena.count && !gArena.blocks[i + 1].used) {
            gArena.blocks[i].size += gArena.blocks[i + 1].size;
            memmove(&gArena.blocks[i + 1], &gArena.blocks[i + 2], (gArena.count - i - 2) * sizeof(Arena::Block));
            --gArena.count;
        }
        if (i > 0 && !gArena.blocks[i - 1].used) {
            gArena.blocks[i - 1].size += gArena.blocks[i].size;
            memmove(&gArena.blocks[i], &gArena.blocks[i + 1], (gArena.count - i - 1) * sizeof(Arena::Block));
            --gArena.count;
        }
        return;
    }
}

// ---- Platform & Board callbacks for Ath11k/mac80211 ----
volatile uint32_t *gCfgVa = nullptr;
uint32_t gPcieCap = 0, gMsiCap = 0;
Window gMsiDbi;
volatile uint32_t gMsiCount = 0, gMsiBits = 0, gMsiPending = 0, gMsiWake = 0;
bool gMsiAttached = false;

uint64_t pNowNs() { uint64_t ns = 0; absolutetime_to_nanoseconds(mach_absolute_time(), &ns); return ns; }
uint64_t pBootNs() { uint64_t ns = 0; absolutetime_to_nanoseconds(mach_continuous_time(), &ns); return ns; }
uint64_t pNow() { return pNowNs() / 1000000ULL; }
void pSleep(unsigned ms) { IOSleep(ms); }
void pBusyDelayUs(unsigned us) { IODelay(us); }
void pHalt() { for (;;) IOSleep(1000); }

void pLog(int level, const char *line) {
    if (level <= 6) {
        printf("LQ103 WIFI[%d] %s\n", level, line);
    }
}

void pPoll() {
    nw_wifi_irq_mode(gMsiAttached ? 1 : 0);
    const uint32_t pending = __atomic_exchange_n(&gMsiPending, 0u, __ATOMIC_ACQ_REL);
    if (pending) nw_wifi_irq_pending(pending);
    nw_wifi_poll();
}

void *hAlloc(size_t n) {
    uint8_t *p = static_cast<uint8_t *>(IOMallocData(n + 16));
    if (!p) return nullptr;
    *reinterpret_cast<size_t *>(p) = n + 16;
    return p + 16;
}
void hFree(void *q) {
    if (!q) return;
    uint8_t *p = static_cast<uint8_t *>(q) - 16;
    IOFreeData(p, *reinterpret_cast<size_t *>(p));
}
void *pDmaAlloc(size_t n, uint64_t *bus) { return arenaAlloc(n, bus); }
void pDmaFree(size_t, void *p, uint64_t) { arenaFree(p); }
uint64_t pDmaMap(void *p, size_t n, int) {
    if (static_cast<uint8_t *>(p) < gArena.va || static_cast<uint8_t *>(p) >= gArena.va + gArena.bytes) return 0;
    if (n) cleanRange(p, n);
    return gArena.iova + (static_cast<uint8_t *>(p) - gArena.va);
}
void pDmaSync(uint64_t bus, size_t n, int) {
    if (bus < gArena.iova || bus + n > gArena.iova + gArena.bytes) return;
    cleanRange(gArena.va + (bus - gArena.iova), n);
}

bool boardMac(uint8_t m[6]) {
    IORegistryEntry *chosen = IORegistryEntry::fromPath("/chosen", gIODTPlane);
    OSData *id = chosen ? OSDynamicCast(OSData, chosen->getProperty("unique-chip-id")) : nullptr;
    uint64_t seed = 0;
    if (id && id->getLength() >= sizeof seed) memcpy(&seed, id->getBytesNoCopy(), sizeof seed);
    OSSafeReleaseNULL(chosen);
    if (!seed) return false;
    uint64_t h = 0xcbf29ce484222325ull;
    for (unsigned i = 0; i < 8; ++i) h = (h ^ ((seed >> (8 * i)) & 0xff)) * 0x100000001b3ull;
    for (unsigned i = 0; i < 6; ++i) m[i] = uint8_t(h >> (8 * i));
    m[0] = uint8_t((m[0] & 0xfe) | 0x02);
    return true;
}

void publishMac() {
    uint8_t m[6];
    if (!boardMac(m)) return;
    if (IORegistryEntry *chosen = IORegistryEntry::fromPath("/chosen", gIODTPlane)) {
        if (!chosen->getProperty("mac-address-wifi0")) chosen->setProperty("mac-address-wifi0", m, sizeof m);
        chosen->release();
    }
    if (IORegistryEntry *wlan = IORegistryEntry::fromPath("/arm-io/wlan", gIODTPlane)) {
        if (!wlan->getProperty("local-mac-address")) wlan->setProperty("local-mac-address", m, sizeof m);
        wlan->release();
    }
}

struct FwCache { char name[32]; uint8_t *data; size_t size; bool tried; } gFw[8];
int pFwGet(const char *path, const uint8_t **data, size_t *size) {
    const char *base = path;
    for (const char *c = path; *c; ++c) if (*c == '/') base = c + 1;
    if (!strcmp(base, "wlan_mac.bin")) {
        static char text[40];
        static size_t len;
        if (!len) {
            uint8_t m[6];
            if (!boardMac(m)) return -1;
            len = size_t(snprintf(text, sizeof text, "address=%02x%02x%02x%02x%02x%02x\n",
                                  m[0], m[1], m[2], m[3], m[4], m[5]));
        }
        *data = reinterpret_cast<const uint8_t *>(text);
        *size = len;
        return 0;
    }
    FwCache *slot = nullptr;
    for (auto &f : gFw) { if (f.tried && !strncmp(f.name, base, sizeof f.name)) { slot = &f; break; } }
    if (!slot) for (auto &f : gFw) { if (!f.tried) { slot = &f; strlcpy(f.name, base, sizeof f.name); f.tried = true; break; } }
    if (!slot) return -1;
    if (!slot->data && slot->size == 0) {
        if (liuqin_wifi_firmware_read(base, &slot->data, &slot->size)) return -1;
        printf("LQ103 WIFI_FW loaded %s bytes=%zu\n", base, slot->size);
    }
    if (!slot->data) return -1;
    *data = slot->data;
    *size = slot->size;
    return 0;
}

bool findCaps() {
    uint8_t cap = uint8_t(gCfgVa[0x34u / 4u] & 0xffu);
    for (unsigned guard = 0; cap >= 0x40u && guard < 48u; ++guard) {
        const uint32_t w = gCfgVa[cap / 4u];
        if (uint8_t(w) == 0x10u) gPcieCap = cap;
        if (uint8_t(w) == 0x05u) gMsiCap = cap;
        cap = uint8_t(w >> 8);
    }
    return gPcieCap && gMsiCap;
}

int pCfgRead(int off, int size, uint32_t *v) {
    uint32_t o = uint32_t(off);
    if (o & 0x80000000u) o = gPcieCap + (o & 0x7fffffffu);
    const uint32_t w = gCfgVa[(o & ~3u) / 4u];
    *v = size == 4 ? w : size == 2 ? (w >> ((o & 2u) * 8u)) & 0xffffu : (w >> ((o & 3u) * 8u)) & 0xffu;
    return 0;
}

int pCfgWrite(int off, int size, uint32_t v) {
    uint32_t o = uint32_t(off);
    if (o & 0x80000000u) o = gPcieCap + (o & 0x7fffffffu);
    if (size == 4) { gCfgVa[o / 4u] = v; dsb(); return 0; }
    const unsigned shift = (size == 2 ? (o & 2u) : (o & 3u)) * 8u;
    const uint32_t mask = (size == 2 ? 0xffffu : 0xffu) << shift;
    gCfgVa[(o & ~3u) / 4u] = (gCfgVa[(o & ~3u) / 4u] & ~mask) | ((v << shift) & mask);
    dsb();
    return 0;
}

int pMsiTarget(uint32_t *lo, uint32_t *hi, uint32_t *data) {
    *lo = uint32_t(gArena.iova);
    *hi = uint32_t(gArena.iova >> 32);
    *data = 0;
    return 0;
}

void msiIrq(void *) {
    const uint32_t status = gMsiDbi.va[kDbiMsiStatus0 / 4u];
    if (status) gMsiDbi.va[kDbiMsiStatus0 / 4u] = status;
    gMsiCount = gMsiCount + 1;
    gMsiBits = gMsiBits | status;
    __atomic_fetch_or(&gMsiPending, status, __ATOMIC_RELEASE);
    static uint32_t empty;
    empty = status ? 0 : empty + 1;
    if (empty > 100000u) { gMsiDbi.va[kDbiMsiEnable0 / 4u] = 0; gMsiAttached = false; }
    __atomic_store_n(&gMsiWake, 1u, __ATOMIC_RELEASE);
    thread_wakeup(event_t(&gMsiWake));
}

int msiAttach() {
    if (!armcpu_spi_attach) return -78;
    if (!gMsiDbi.va && !gMsiDbi.open(kDbiBase, 0x1000u)) return -12;
    gMsiDbi.va[kDbiMsiAddrLo / 4u] = uint32_t(gArena.iova);
    gMsiDbi.va[kDbiMsiAddrHi / 4u] = uint32_t(gArena.iova >> 32);
    gMsiDbi.va[kDbiMsiMask0 / 4u] = 0u;
    gMsiDbi.va[kDbiMsiEnable0 / 4u] = 0xffffffffu;
    dsb();
    const int rc = armcpu_spi_attach(32u + kMsiSpi, false, msiIrq, nullptr, nullptr, nullptr);
    gMsiAttached = (rc == 0);
    return rc;
}

void msiWait(unsigned ms) {
    if (__atomic_exchange_n(&gMsiWake, 0u, __ATOMIC_ACQ_REL)) return;
    assert_wait_timeout(event_t(&gMsiWake), THREAD_UNINT, ms, NSEC_PER_MSEC);
    if (__atomic_exchange_n(&gMsiWake, 0u, __ATOMIC_ACQ_REL)) { clear_wait(current_thread(), THREAD_AWAKENED); return; }
    thread_block(THREAD_CONTINUE_NULL);
    __atomic_store_n(&gMsiWake, 0u, __ATOMIC_RELEASE);
}

// ---- kern_ctl control socket for unixnu-wpa_supplicant ----
struct ControlClient { uint64_t session; uint32_t unit; };
kern_ctl_ref gControlRef;
IOLock *gControlLock;
ControlClient *gControlClient;
volatile uint32_t gCtlRxTotal, gCtlTxTotal;

errno_t controlError(int status) {
    switch (status) {
        case NW_CONTROL_OK: return 0;
        case NW_CONTROL_INVALID: return EINVAL;
        case NW_CONTROL_BUSY: return EWOULDBLOCK;
        case NW_CONTROL_NOT_READY: return ENXIO;
        case NW_CONTROL_AUTH_FAILED: return EACCES;
        case NW_CONTROL_TIMED_OUT: return ETIMEDOUT;
        case NW_CONTROL_UNSUPPORTED: return EOPNOTSUPP;
        case NW_CONTROL_NO_MEMORY: return ENOBUFS;
        case NW_CONTROL_NOT_FOUND: return ENOENT;
        case NW_CONTROL_STALE: return ESTALE;
        default: return EIO;
    }
}
errno_t controlConnect(kern_ctl_ref, sockaddr_ctl *address, void **information) {
    auto *owner = static_cast<ControlClient *>(IOMalloc(sizeof(ControlClient)));
    if (!owner) return ENOMEM;
    const int status = nw_wifi_control_attach(&owner->session);
    if (status) { IOFree(owner, sizeof(*owner)); return controlError(status); }
    owner->unit = address->sc_unit;
    IOLockLock(gControlLock); gControlClient = owner; IOLockUnlock(gControlLock);
    *information = owner;
    printf("LQ103 WIFI_CTL connected session=%llu unit=%u\n", (unsigned long long)owner->session, owner->unit);
    return 0;
}
errno_t controlDisconnect(kern_ctl_ref, uint32_t, void *information) {
    if (!information) return 0;
    auto *owner = static_cast<ControlClient *>(information);
    nw_wifi_control_detach(owner->session);
    IOLockLock(gControlLock); if (gControlClient == owner) gControlClient = nullptr; IOLockUnlock(gControlLock);
    IOFree(owner, sizeof(*owner));
    return 0;
}
int controlReadMbuf(void *source, void *destination, size_t length) {
    return mbuf_copydata(static_cast<mbuf_t>(source), 0, length, destination);
}
errno_t controlReceive(kern_ctl_ref, uint32_t, void *information, mbuf_t packet, int) {
    auto *owner = static_cast<ControlClient *>(information);
    __atomic_add_fetch(&gCtlRxTotal, 1u, __ATOMIC_RELAXED);
    const int status = nw_wifi_control_receive(owner->session, mbuf_pkthdr_len(packet), controlReadMbuf, packet);
    mbuf_freem(packet);
    return controlError(status);
}
void controlReceived(kern_ctl_ref, uint32_t, void *information, int) {
    nw_wifi_control_writable(static_cast<ControlClient *>(information)->session);
}
errno_t controlGetOption(kern_ctl_ref, uint32_t, void *information, int option, void *bytes, size_t *length) {
    if (option != NW_CONTROL_GET_SESSION) return ENOPROTOOPT;
    if (!length) return EINVAL;
    if (!bytes || *length < sizeof(uint64_t)) { *length = sizeof(uint64_t); return EMSGSIZE; }
    const uint64_t session = static_cast<ControlClient *>(information)->session;
    memcpy(bytes, &session, sizeof(session));
    *length = sizeof(session);
    return 0;
}
int controlSend(void *, uint64_t session, const void *bytes, size_t length) {
    IOLockLock(gControlLock);
    const bool active = gControlClient && gControlClient->session == session;
    const uint32_t unit = active ? gControlClient->unit : 0;
    IOLockUnlock(gControlLock);
    if (!active) return NW_CONTROL_SEND_CLOSED;
    const errno_t result = ctl_enqueuedata(gControlRef, unit, const_cast<void *>(bytes), length, CTL_DATA_EOR);
    if (!result) {
        __atomic_add_fetch(&gCtlTxTotal, 1u, __ATOMIC_RELAXED);
        return NW_CONTROL_SEND_OK;
    }
    if (result == ENOBUFS || result == EWOULDBLOCK) return NW_CONTROL_SEND_AGAIN;
    return NW_CONTROL_SEND_CLOSED;
}
void controlWake(void *) {
    __atomic_store_n(&gMsiWake, 1u, __ATOMIC_RELEASE);
    thread_wakeup(event_t(&gMsiWake));
}
int controlStart() {
    if (gControlRef) return 0;
    if (!gControlLock) gControlLock = IOLockAlloc();
    if (!gControlLock) return ENOMEM;
    kern_ctl_reg reg {};
    snprintf(reg.ctl_name, sizeof(reg.ctl_name), "%s", NW_CONTROL_NAME);
    reg.ctl_flags = CTL_FLAG_PRIVILEGED | CTL_FLAG_REG_EXTENDED;
    reg.ctl_sendsize = 256 * 1024;
    reg.ctl_recvsize = 512 * 1024;
    reg.ctl_connect = controlConnect;
    reg.ctl_disconnect = controlDisconnect;
    reg.ctl_send = controlReceive;
    reg.ctl_getopt = controlGetOption;
    reg.ctl_rcvd = controlReceived;
    const errno_t result = ctl_register(&reg, &gControlRef);
    if (result) return result;
    const nw_control_transport transport { nullptr, controlSend, controlWake };
    const int status = nw_wifi_control_transport_set(&transport);
    if (status) { ctl_deregister(gControlRef); gControlRef = nullptr; return controlError(status); }
    return 0;
}

void wifiPcieWorker(void *, wait_result_t) {
    thread_set_thread_name(current_thread(), "liuqin-wifi");
    publishMac();
    IOSleep(1500);

    int pwr = liuqin_wcn_power_get(LIUQIN_WCN_WLAN);
    if (pwr) { printf("LQ103 WIFI_PCIE wcn_power fail err=%d\n", pwr); return; }
    IOSleep(10);

    Window gcc, tlmm;
    if (!gcc.open(kGccBase, 0x100000u) || !tlmm.open(kTlmmBase, 0x100000u)) {
        printf("LQ103 WIFI_PCIE map gcc/tlmm fail\n");
        return;
    }
    volatile uint32_t *g = gcc.va;
    volatile uint32_t *t = tlmm.va;

    setPin(t, kPerstGpio, 1u | (1u << 9), 0);
    setPin(t, kClkReqGpio, 3u | (1u << 2), -1);
    setPin(t, kWakeGpio, 3u, -1);
    setPin(t, kWlanEnGpio, 1u | (3u << 6) | (1u << 9), 0);
    IOSleep(150);
    setPin(t, kWlanEnGpio, 1u | (3u << 6) | (1u << 9), 1);
    IOSleep(60);

    g[kGdsc / 4u] &= ~1u;
    dsb();
    for (unsigned i = 0; i < 500 && !(g[kGdsc / 4u] & (1u << 31)); ++i) IODelay(20);
    const uint32_t gdscVal = g[kGdsc / 4u];
    if (!(gdscVal & (1u << 31))) { printf("LQ103 WIFI_PCIE gdsc timeout val=0x%x\n", gdscVal); return; }

    g[(kAuxRcg + 4u) / 4u] = 0u; dsb(); g[kAuxRcg / 4u] |= 1u;
    g[(kRchngRcg + 4u) / 4u] = (1u << 8) | 11u; dsb(); g[kRchngRcg / 4u] |= 1u;
    dsb();
    (void)waitClear(&g[kAuxRcg / 4u], 1u, 100);
    (void)waitClear(&g[kRchngRcg / 4u], 1u, 100);

    g[kPipeMux / 4u] = (g[kPipeMux / 4u] & ~3u) | 2u;
    g[kVote8 / 4u] |= (kVote8Bits & ~(1u << 4));
    g[kVote0 / 4u] |= kVote0Bits;
    g[kClkrefEn / 4u] |= 1u;
    dsb();
    IODelay(500);

    uint32_t offMask = 0;
    for (unsigned i = 0; i < sizeof(kCheckBranches) / sizeof(kCheckBranches[0]); ++i) {
        if (g[kCheckBranches[i] / 4u] & (1u << 31)) offMask |= (1u << i);
    }
    if (offMask) { printf("LQ103 WIFI_PCIE branch halt fail off=0x%x\n", offMask); return; }

    pulseReset(g, kPcieBcr);

    Window parf, dbi, phy;
    if (!parf.open(kParfBase, 0x3000u) || !dbi.open(kDbiBase, 0x1000u) || !phy.open(kPhyBase, 0x2000u)) {
        printf("LQ103 WIFI_PCIE map parf/dbi/phy fail\n");
        return;
    }
    volatile uint32_t *f = parf.va;
    volatile uint32_t *d = dbi.va;
    volatile uint32_t *p = phy.va;

    f[kParfDeviceType / 4u] = 4u;
    f[kParfPhyCtrl / 4u] &= ~1u;
    f[kParfDbiBaseV2 / 4u] = uint32_t(kDbiBase);
    f[kParfDbiBaseV2Hi / 4u] = uint32_t(kDbiBase >> 32);
    f[kParfAtuBase / 4u] = uint32_t(kAtuBase);
    f[kParfAtuBaseHi / 4u] = uint32_t(kAtuBase >> 32);
    f[kParfSlvSpaceV2 / 4u] = 0u;
    f[kParfSlvSpaceV2Hi / 4u] = kSlvSpaceSz;
    f[kParfSysCtrl / 4u] &= ~(1u << 29);
    f[kParfMhiClkReset / 4u] |= (1u << 4);
    f[kParfPmCtrl / 4u] &= ~(1u << 5);
    f[kParfAxiHaltV2 / 4u] |= (1u << 31);
    dsb();

    g[0x7c020u / 4u] &= ~1u;
    g[0x7c028u / 4u] &= ~1u;
    pulseReset(g, kPhyBcr);

    using namespace liuqin_wifi_phy;
    p[kPowerDownControl / 4u] |= 3u;
    dsb();
    for (const Init &e : kSerdes) p[e.offset / 4u] = e.value;
    for (const Init &e : kTx)     p[e.offset / 4u] = e.value;
    for (const Init &e : kRx)     p[e.offset / 4u] = e.value;
    for (const Init &e : kPcs)    p[e.offset / 4u] = e.value;
    for (const Init &e : kPcsMisc) p[e.offset / 4u] = e.value;
    dsb();

    g[kVote8 / 4u] |= (1u << 4);
    g[kPipeMux / 4u] &= ~3u;
    dsb();
    p[kSwReset / 4u] &= ~1u;
    dsb();
    p[kStartControl / 4u] |= 3u;
    dsb();
    IODelay(1200);

    unsigned phyPolls = 0;
    const bool phyReady = waitClear(&p[kPcsStatus1 / 4u], 1u << 6, 200, &phyPolls);
    printf("LQ103 WIFI_PCIE phy ready=%u pcs_st1=0x%x polls=%u pipe_halt=0x%x\n",
           phyReady ? 1u : 0u, p[kPcsStatus1 / 4u], phyPolls, g[kPipeHalt / 4u]);
    phy.close();
    if (!phyReady) return;

    for (unsigned i = 0; i < 256u; ++i) f[(kParfBdfToSidTable + 4u * i) / 4u] = 0u;
    f[kParfBdfToSidCfg / 4u] &= ~1u;
    const uint8_t bdfHash = crc8Bdf(0x0100u);
    f[(kParfBdfToSidTable + 4u * bdfHash) / 4u] = (0x0100u << 16) | (1u << 8);
    dsb();

    // Clear RC BAR0/BAR1 and disable IO + Prefetchable Memory windows so inbound DMA is never shadowed
    d[0x8bcu / 4u] |= 1u; // MISC_CONTROL_1_OFF: DBI_RO_WR_EN
    dsb();
    d[0x10u / 4u] = 0u;
    d[0x14u / 4u] = 0u;
    d[kDbiBusNumbers / 4u] = 0x00010100u;
    d[0x1cu / 4u] = (d[0x1cu / 4u] & 0xffff0000u) | 0x00f0u; // IO base > limit (disabled)
    d[0x24u / 4u] = 0x0000fff0u; // Prefetchable mem base > limit (disabled)
    d[kDbiCommand / 4u] |= 0x6u;
    d[0x8bcu / 4u] &= ~1u;
    dsb();

    IOSleep(100);
    setPin(t, kPerstGpio, 1u | (1u << 9), 1);
    IODelay(1000);
    f[kParfLtssm / 4u] |= (1u << 8);
    dsb();

    unsigned linkMs = 0;
    bool linkUp = false;
    for (; linkMs < 1000u; ++linkMs) {
        if ((d[kDbiPortDebug1 / 4u] & (1u << 4)) && ((d[kDbiPortDebug0 / 4u] & 0x3fu) == 0x11u)) {
            linkUp = true;
            break;
        }
        IOSleep(1);
    }
    printf("LQ103 WIFI_PCIE link up=%u ms=%u lnksta=0x%x ltssm=0x%x\n",
           linkUp ? 1u : 0u, linkMs, d[kDbiLinkCtrlSta / 4u], f[kParfLtssm / 4u]);
    if (!linkUp) return;

    Window atu, cfg;
    if (!atu.open(kAtuBase, 0x1000u) || !cfg.open(kCfgBase, 0x1000u)) {
        printf("LQ103 WIFI_PCIE map atu/cfg fail\n");
        return;
    }
    volatile uint32_t *a = atu.va;
    // Disable all inbound iATU windows (0..7) so inbound DMA passes straight through to AXI/SMMU
    uint32_t ibMask = 0;
    for (unsigned i = 0; i < 8u; ++i) {
        if (a[(0x200u * i + 0x104u) / 4u] & (1u << 31)) ibMask |= (1u << i);
        a[(0x200u * i + 0x104u) / 4u] = 0u;
    }
    dsb();
    a[0x08u / 4u] = uint32_t(kCfgBase);
    a[0x0cu / 4u] = uint32_t(kCfgBase >> 32);
    a[0x10u / 4u] = uint32_t(kCfgBase + 0xfffffu);
    a[0x20u / 4u] = uint32_t((kCfgBase + 0xfffffu) >> 32);
    a[0x14u / 4u] = 1u << 24;
    a[0x18u / 4u] = 0u;
    a[0x00u / 4u] = 0x4u;
    a[0x04u / 4u] = 1u << 31;
    dsb();
    for (unsigned i = 0; i < 10 && !(a[0x04u / 4u] & (1u << 31)); ++i) IODelay(10);

    const uint32_t epId = cfg.va[0];
    printf("LQ103 WIFI_PCIE ep id=0x%08x subsys=0x%08x\n", epId, cfg.va[0x2cu / 4u]);
    if ((epId & 0xffffu) != 0x17cbu) return;

    volatile uint32_t *r1 = a + (0x200u / 4u);
    r1[0x08u / 4u] = uint32_t(kMemBase);
    r1[0x0cu / 4u] = uint32_t(kMemBase >> 32);
    r1[0x10u / 4u] = uint32_t(kMemBase + kMemSize - 1u);
    r1[0x20u / 4u] = uint32_t((kMemBase + kMemSize - 1u) >> 32);
    r1[0x14u / 4u] = uint32_t(kMemBase);
    r1[0x18u / 4u] = uint32_t(kMemBase >> 32);
    r1[0x00u / 4u] = 0x0u;
    r1[0x04u / 4u] = 1u << 31;
    dsb();
    for (unsigned i = 0; i < 10 && !(r1[0x04u / 4u] & (1u << 31)); ++i) IODelay(10);
    d[kDbiMemBaseLimit / 4u] = uint32_t(((kMemBase + kMemSize - 1u) & 0xfff00000u) |
                                        ((kMemBase >> 16) & 0xfff0u));
    dsb();

    const uint32_t savedBar0 = cfg.va[0x10u / 4u];
    cfg.va[0x10u / 4u] = 0xffffffffu;
    dsb();
    const uint32_t barMask = cfg.va[0x10u / 4u];
    cfg.va[0x10u / 4u] = savedBar0;
    const uint32_t barSize = ~(barMask & ~0xfu) + 1u;
    if (!(barMask & ~0xfu) || !barSize || barSize > kMemSize) return;
    const uint32_t barAddr = uint32_t((kMemBase + barSize - 1u) & ~uint64_t(barSize - 1u));
    cfg.va[0x10u / 4u] = barAddr | (barMask & 0xfu);
    if ((barMask & 6u) == 4u) cfg.va[0x14u / 4u] = 0u;
    cfg.va[0x04u / 4u] = (cfg.va[0x04u / 4u] & 0xffffu) | 0x6u;
    dsb();

    // Set up 128 MiB Apps SMMU Stage-1 32-bit DMA window for SID 0x1c01
    if (!setupSmmuDmaWindow(kWifiSmmuSid)) return;

    Window bar;
    const uint32_t mapSz = barSize < 0x200000u ? barSize : 0x200000u;
    if (!bar.open(barAddr, mapSz)) { printf("LQ103 WIFI_PCIE bar0 map fail\n"); return; }

    gCfgVa = cfg.va;
    if (!findCaps()) { printf("LQ103 WIFI_PCIE caps missing\n"); return; }

    // Wait for NGPUADD2 addon to finish unpacking WCN6855 firmware
    for (unsigned i = 0; i < 240; ++i) {
        const uint8_t *fw = nullptr;
        size_t sz = 0;
        if (!pFwGet("amss.bin", &fw, &sz) && sz > 0) break;
        IOSleep(500);
    }

    static const struct lx_platform plat = {
        pNow, pSleep, pPoll, pLog, pHalt, hAlloc, hFree,
        pDmaAlloc, pDmaFree, pDmaMap, pDmaSync, pFwGet,
        pNowNs, pBootNs, pBusyDelayUs, _disable_preemption, _enable_preemption
    };
    nw_wifi_set_platform(&plat);

    const int ctlErr = controlStart();
    printf("LQ103 WIFI_CTL register rc=%d\n", ctlErr);

    static struct nw_board board {};
    board.bar = const_cast<uint32_t *>(bar.va);
    board.bar_len = mapSz;
    board.device_id = uint16_t(epId >> 16);
    board.msi_cap = uint16_t(gMsiCap);
    board.irq_base = 1000;
    board.cfg_read = pCfgRead;
    board.cfg_write = pCfgWrite;
    board.msi_target = pMsiTarget;
    board.map_phys = nullptr;

    const int rc = nw_wifi_start(&plat, &board);
    printf("LQ103 WIFI_STACK start rc=%d stage=%u\n", rc, nw_wifi_stats.stage);
    if (rc) {
        volatile uint32_t *m = bar.va;
        const uint32_t bhi = m[0x28u / 4u];
        const uint32_t bhie = m[0x2cu / 4u];
        printf("LQ103 WIFI_DIAG mhi(ctrl=0x%x st=0x%x bhi=0x%x bhie=0x%x) cfg(id=0x%x cmd=0x%x bar0=0x%x) dbi(cmd=0x%x bar0=0x%x mem=0x%x pref=0x%x dbg0=0x%x dbg1=0x%x aer=0x%x/0x%x)\n",
               m[0x38u / 4u], m[0x48u / 4u], bhi, bhie,
               cfg.va[0], cfg.va[1], cfg.va[0x10u / 4u],
               d[1], d[0x10u / 4u], d[0x20u / 4u], d[0x24u / 4u],
               d[kDbiPortDebug0 / 4u], d[kDbiPortDebug1 / 4u], d[0x104u / 4u], d[0x110u / 4u]);
        printf("LQ103 WIFI_DIAG parf(sys=0x%x pm=0x%x mhirst=0x%x halt=0x%x q2a=0x%x sidoff=0x%x bdft=0x%x nosnp=0x%x sidcfg=0x%x sident=0x%x hash=0x%x ib=0x%x) sink0=0x%x\n",
               f[kParfSysCtrl / 4u], f[kParfPmCtrl / 4u], f[kParfMhiClkReset / 4u], f[kParfAxiHaltV2 / 4u],
               f[0x1acu / 4u], f[0x234u / 4u], f[0x24cu / 4u], f[0x3d4u / 4u],
               f[kParfBdfToSidCfg / 4u], f[(kParfBdfToSidTable + 4u * bdfHash) / 4u], bdfHash, ibMask,
               *reinterpret_cast<volatile uint32_t *>(gArena.va));
        printf("LQ103 WIFI_DIAG gcc(tbu=0x%x agg0=0x%x agg1=0x%x cfgahb=0x%x mstr=0x%x slv=0x%x q2a=0x%x)\n",
               g[0x9d094u / 4u], g[0x7b08cu / 4u], g[0x9d098u / 4u], g[0x20030u / 4u],
               g[0x7b028u / 4u], g[0x7b020u / 4u], g[0x7b01cu / 4u]);
        if (bhi && bhi + 0x40u <= mapSz) {
            printf("LQ103 WIFI_DIAG bhi(imglo=0x%x imghi=0x%x imgsz=0x%x db=0x%x ee=0x%x st=0x%x err=0x%x dbg=0x%x/0x%x/0x%x intvec=0x%x)\n",
                   m[(bhi + 0x08u) / 4u], m[(bhi + 0x0cu) / 4u], m[(bhi + 0x10u) / 4u], m[(bhi + 0x18u) / 4u],
                   m[(bhi + 0x28u) / 4u], m[(bhi + 0x2cu) / 4u], m[(bhi + 0x30u) / 4u],
                   m[(bhi + 0x34u) / 4u], m[(bhi + 0x38u) / 4u], m[(bhi + 0x3cu) / 4u], m[(bhi + 0x20u) / 4u]);
        }
        Window smmu;
        if (smmu.open(kSmmuBase, 0x100000u)) {
            volatile uint32_t *s = smmu.va;
            const uint32_t idr0 = s[0x20u / 4u];
            const uint32_t idr1 = s[0x24u / 4u];
            const uint32_t numSmr = idr0 & 0xffu;
            const uint32_t pageSz = (idr1 >> 31) ? 0x10000u : 0x1000u;
            const uint32_t numPages = 1u << (((idr1 >> 28) & 7u) + 1u);
            const uint32_t cbOff = (numPages + gArena.smmuBank) * pageSz;
            volatile uint32_t *cb = s + (cbOff / 4u);
            printf("LQ103 WIFI_DIAG smmu scr0=0x%x gfsr=0x%x gfar=0x%x:%08x gfsynr=0x%x/0x%x smr=0x%x s2cr=0x%x cb%u(sctlr=0x%x tcr=0x%x tcr2=0x%x fsr=0x%x far=0x%x:%08x fsynr0=0x%x)\n",
                   s[0], s[0x48u / 4u], s[0x44u / 4u], s[0x40u / 4u], s[0x50u / 4u], s[0x54u / 4u],
                   s[(0x800u + 4u * gArena.smmuSlot) / 4u], s[(0xc00u + 4u * gArena.smmuSlot) / 4u],
                   gArena.smmuBank, cb[0], cb[0x30u / 4u], cb[0x10u / 4u], cb[0x58u / 4u],
                   cb[0x64u / 4u], cb[0x60u / 4u], cb[0x68u / 4u]);
            for (uint32_t i = 0; i < numSmr && i < 128u; ++i) {
                const uint32_t smr = s[(0x800u + 4u * i) / 4u];
                if (smr & (1u << 31))
                    printf("LQ103 WIFI_DIAG smr[%u]=0x%x s2cr=0x%x\n", i, smr, s[(0xc00u + 4u * i) / 4u]);
            }
            // Fault probe: disable our SMR slot, re-ring BHI_IMGTXDB, and see if Apps SMMU catches the SID+IOVA
            if (bhi && bhi + 0x40u <= mapSz) {
                s[0x48u / 4u] = 0xffffffffu;
                s[(0x800u + 4u * gArena.smmuSlot) / 4u] = 0u;
                dsb();
                m[(bhi + 0x2cu) / 4u] = 0u;
                m[(bhi + 0x08u) / 4u] = uint32_t(kDmaIovaBase + 0x500000u);
                m[(bhi + 0x0cu) / 4u] = 0u;
                m[(bhi + 0x10u) / 4u] = 0x1000u;
                m[(bhi + 0x18u) / 4u] = 0x1234567u;
                dsb();
                IOSleep(100);
                printf("LQ103 WIFI_DIAG probe gfsr=0x%x gfar=0x%x:%08x gfsynr=0x%x/0x%x bhi_st=0x%x bhi_err=0x%x\n",
                       s[0x48u / 4u], s[0x44u / 4u], s[0x40u / 4u], s[0x50u / 4u], s[0x54u / 4u],
                       m[(bhi + 0x2cu) / 4u], m[(bhi + 0x30u) / 4u]);
            }
        }
        return;
    }

    const int msiRc = msiAttach();
    nw_wifi_irq_mode(gMsiAttached ? 1 : 0);
    printf("LQ103 WIFI_MSI attach rc=%d spi=%u\n", msiRc, kMsiSpi);

    bool netDone = false;
    uint64_t nextReport = pNow() + 10000ULL;
    uint64_t sliceStart = pNowNs();
    for (;;) {
        const int busy = nw_wifi_step();
        if (!netDone && nw_wifi_stats.stage >= 4) {
            netDone = true;
            nw_wifi_status st {};
            nw_wifi_status_get(&st);
            printf("LQ103 WIFI_READY mac=%02x:%02x:%02x:%02x:%02x:%02x chans=%u\n",
                   st.mac[0], st.mac[1], st.mac[2], st.mac[3], st.mac[4], st.mac[5], st.channels);
            sheng_wifi_net_start(st.mac);
        }
        if (!busy) {
            if (gMsiAttached) {
                const unsigned wait = nw_wifi_wait_ms(1000);
                if (wait) msiWait(wait);
            } else {
                IOSleep(1);
            }
            sliceStart = pNowNs();
        } else if (pNowNs() - sliceStart >= 2000000ULL) {
            thread_yield_to_preemption();
            sliceStart = pNowNs();
        }
        const uint64_t now = pNow();
        if (now >= nextReport) {
            nextReport = now + 20000ULL;
            nw_control_stats cs {};
            nw_wifi_control_stats_get(&cs);
            printf("LQ103 WIFI_STAT stage=%u scans=%u bss=%u msi=%u(bits=0x%x) dma=%zu/%zuK ctl(sess=%llu rx=%u tx=%u)\n",
                   nw_wifi_stats.stage, nw_wifi_stats.scans, nw_wifi_stats.bss_seen,
                   gMsiCount, gMsiBits, gArena.used >> 10, gArena.bytes >> 10,
                   (unsigned long long)cs.active_session, gCtlRxTotal, gCtlTxTotal);
        }
    }
}

uint32_t gWifiStarted = 0;

} // namespace

extern "C" void native_wifi_logf(int level, const char *fmt, ...) {
    char line[160];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(line, sizeof line, fmt, ap);
    va_end(ap);
    pLog(level, line);
}

extern "C" int sheng_wifi_file(const char *name, const uint8_t **data, size_t *size) {
    return pFwGet(name, data, size);
}

extern "C" void sheng_wifi_wake(void) {
    __atomic_store_n(&gMsiWake, 1u, __ATOMIC_RELEASE);
    thread_wakeup(event_t(&gMsiWake));
}

extern "C" void liuqin_wifi_pcie_start(void) {
    uint32_t expected = 0;
    if (!__atomic_compare_exchange_n(&gWifiStarted, &expected, 1u, false, __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE))
        return;
    thread_t th = nullptr;
    if (kernel_thread_start(wifiPcieWorker, nullptr, &th) == KERN_SUCCESS)
        thread_deallocate(th);
}
