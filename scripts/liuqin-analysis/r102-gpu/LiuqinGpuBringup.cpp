// SPDX-License-Identifier: BSD-2-Clause-Patent
// SM8475 / Adreno 730.1 (Xiaomi Pad 6 Pro, liuqin) native GPU KMD bring-up.
// Ported from UniXNU-sheng/package/GpuPowerProbe.cpp for SM8475 hardware facts measured in r102-p12.
// Keeps writable __DATA minimal (large state heap-allocated) so XNU standalone __DATA stays under 0x284000.

#include <IOKit/IODeviceMemory.h>
#include <IOKit/IODeviceTreeSupport.h>
#include <IOKit/IOLib.h>
#include <IOKit/IOMemoryDescriptor.h>
#include <IOKit/IOPlatformExpert.h>
#include <IOKit/IOService.h>
#include <IOKit/IOUserClient.h>
#include <kern/clock.h>
#include <kern/thread.h>
#include <kern/thread_call.h>
#include <libkern/c++/OSMetaClass.h>
#include <libkern/c++/OSSharedPtr.h>
#include <libkern/c++/OSSymbol.h>
#include <libkern/crypto/sha2.h>
#include <mach/kmod.h>
#include <mach/mach_time.h>
#include <pexpert/pexpert.h>
#include <stdint.h>
#include <string.h>

extern "C" {
#include "LiuqinGpuPowerBoard.h"
#include "LiuqinA730HwInit.h"
#include "ShengGmu.h"
#include "ShengGmuCommandDb.h"
#include "ShengGmuVotes.h"
#include "AdrenoPM4.h"
}

#include "NativeAdrenoA740HwInit.h"
#include "NativeAdrenoCpInit.h"
#include "NativeAdrenoGmuContext.h"
#include "NativeAdrenoGpuContext.h"
#include "NativeAdrenoMemory.h"
#include "NativeAdrenoPwrup.h"
#include "NativeAdrenoRing.h"
#include "NativeAdrenoSubmit.h"
#include "NativeAdrenoTimer.h"
#include "NativeAdrenoUserClient.h"
#include "NativeAdrenoVm.h"

extern "C" {
uint64_t liuqin_debug_total(void);
uint64_t liuqin_r102_usb_completed(void);
int get_preemption_level(void);
vm_offset_t ml_io_map_unmappable(vm_offset_t phys_addr, vm_size_t size, unsigned int flags);
void ml_io_unmap(vm_offset_t addr, vm_size_t size);
vm_offset_t phystokv(uint64_t pa);
vm_offset_t ml_static_ptovirt(vm_offset_t pa);
extern uint64_t gPhysBase, gPhysSize;
unsigned int pmap_cache_attributes(unsigned int pn);
kern_return_t OSKextLoadKextWithIdentifier(const char *);
extern kmod_info_t g_kernel_kmod_info;

// Hooks consumed by drivers/Adreno740
volatile uint32_t native_gpu_dcvs[15];
volatile uint64_t native_adreno_fence_phys = 0;
int boot_log_export_put(uint32_t, uint32_t, uint32_t, const void *, uint32_t) { return -1; }
unsigned int native_pmap_user_mappings(ppnum_t, void **, uint64_t *, char *) { return 0; }

// External Adreno740 & firmware symbols
extern const uint8_t native_adreno_firmware_image[];
extern const uint64_t native_adreno_firmware_image_size;
extern const uint8_t native_adreno_sqe_firmware_image[];
extern const uint64_t native_adreno_sqe_firmware_image_size;
extern const uint8_t native_adreno_zap_image[];
extern const uint64_t native_adreno_zap_image_size;

extern volatile uint32_t native_adreno_diag;
extern volatile uint32_t native_adreno_wc_enabled;
extern volatile uint32_t native_adreno_owned_coherent;
extern volatile uint32_t native_adreno_io_coherent;
extern volatile uint32_t native_adreno_walk_coherent[3];
extern volatile uint32_t native_adreno_cp_aperture[4];
extern int (*native_adreno_dram_read32)(uint64_t, uint32_t *);
extern int (*native_adreno_cached_read32)(uint64_t, uint32_t *);
extern int (*native_adreno_line_audit)(uint64_t, size_t, uint32_t *, uint32_t *);

IOReturn native_adreno_publish(NativeAdrenoVm *, NativeAdrenoSubmit *, NativeAdrenoRing *,
                               const NativeAdrenoRingClock *, const NativeAdrenoTimer *,
                               const NativeAdrenoAbiDeviceInfo *, uint32_t, uint32_t);
uint32_t native_adreno_publish_stats(uint32_t *);
IOService *native_adreno_published_service(void);
void native_adreno_set_restart(NativeAdrenoRestart, void *);

void native_adreno_accelerator_static_init(void) __asm__("__GLOBAL__sub_I_NativeAdrenoAccelerator.cpp");
IOService *native_adreno_accelerator_allocate(void);
unsigned native_adreno_accelerator_instance_size(void);

IOReturn armcpu_spi_attach(uint32_t intid, bool edge, void (*handler)(void *), void *context,
                           uint32_t *readback, uint64_t *router) __attribute__((weak));

bool native_adreno_fences(uint32_t *, uint32_t *);
extern volatile uint32_t native_adreno_recovery[8];
extern volatile uint32_t native_adreno_recovery_fault[5];
extern volatile uint32_t native_adreno_table_switches[8];
extern volatile uint32_t native_adreno_cp_check[6];
extern volatile uint32_t native_adreno_view_diag[6];
extern volatile uint32_t native_adreno_wc_audit[6];
extern volatile uint32_t native_adreno_coherence[8];
extern volatile uint32_t native_adreno_ib_log[4][4 + 28];
extern volatile uint32_t native_adreno_ib_log_count;
struct LqMetalDiag {
    uint32_t opens, busy, bad, closes, reports, property_reads, foreign_opens, foreign_type,
             name_reads, calls, last_selector, last_status, ext_entries, ext_selector, ext_status,
             ext_in, ext_out, tunnel_calls, probes, sel_bits[8], mb_maps, mb_calls, marks_total,
             marks[16], chk_macf, chk_res, chk_type, type_pass_lo, type_pass_hi, attach_status,
             inflight, inflight_since_calls, forced_unmaps;
    char opener[3][17], reader[3][17], name_reader[17], starter[3][17], report[64], report2[64];
    uint32_t grants;
};
extern LqMetalDiag native_adreno_metal_diag;
struct NativeAdrenoOpenRecord { char name[20]; uint32_t type, macf, res, attach, foreign; };
struct NativeAdrenoClientRecord { char name[20]; uint32_t opens, refused, closes, slot, peak_mib, last_refusal; };
struct NativeAdrenoClientText { char name[20]; char text[64]; };
extern NativeAdrenoOpenRecord native_adreno_open_log[8];
extern volatile uint32_t native_adreno_open_log_count;
extern NativeAdrenoClientRecord native_adreno_client_log[8];
extern NativeAdrenoClientText native_adreno_client_text[8];
extern volatile uint32_t native_legacy_stage, native_legacy_swap_accepted_count,
                         native_legacy_swap_rejected_count, native_legacy_rej_reason,
                         native_legacy_transfer_calls, native_legacy_retirement_calls,
                         native_legacy_frame_count, native_legacy_client_calls,
                         native_legacy_swapstat[16], native_legacy_call_diag[16],
                         native_legacy_pm_stage, native_legacy_pm_calls,
                         native_legacy_pm_callbacks, native_legacy_pm_ordinal;
extern volatile int native_legacy_transfer_status, native_legacy_pm_status;
extern volatile uint64_t native_legacy_copy_n, native_legacy_rej_surface[7];
extern volatile uint32_t native_legacy_rej_state[3], native_legacy_rej_options[3],
                         native_legacy_rej_size[2], native_legacy_rej_rects[2][4];
extern unsigned native_legacy_prepare_report(char *out, unsigned cap);
extern unsigned native_legacy_fb_diag(char *out, unsigned cap);
extern uint32_t native_legacy_hotplug_state(void);
extern uint64_t native_legacy_vsync_head(void);
}

namespace {

constexpr uint32_t kChipIdA730 = 0x07030001u;
constexpr uint64_t kSmmuWindow = 0x40000ULL;
constexpr uint64_t kCmdDbBase = 0x80860000ULL;
constexpr uint64_t kCmdDbBytes = 0x20000ULL;
constexpr uint64_t kZapPhys = 0x8b91a000ULL;
constexpr uint64_t kZapBytes = 0x2000ULL;
constexpr uint32_t kGpuPasId = 13u;

constexpr unsigned kGmuBank = 1, kGmuAsid = 1, kGmuSlot = 2, kGmuSid = 5;
constexpr uint64_t kPhys[5] = {GPB_GCC_GPU_PAGE, GPB_GCC_VOTE_PAGE, GPB_GPUCC_BASE, GPB_SMMU_BASE, GPB_GPU_BASE};
constexpr uint64_t kLen[5]  = {0x1000, 0x1000, GPB_GPUCC_SIZE, GPB_SMMU_GR0_SIZE, GPB_GPU_WINDOW};

constexpr uint64_t kColdPhys[5] = {0x03d6a000ULL, 0x03d50000ULL, 0x0b290000ULL, 0x03d00000ULL, 0x03d9e000ULL};
constexpr uint64_t kColdLen[5]  = {0x35000ULL,    0x10000ULL,    0x10000ULL,    0x40000ULL,    0x1000ULL};

constexpr uint32_t kGmuReg(uint32_t dword) { return dword * 4u - 0x6a000u; }
constexpr uint32_t kGmuSysReset  = kGmuReg(0x1f800);
constexpr uint32_t kGmuHfiStatus = kGmuReg(0x1f980);
constexpr uint32_t kRsccSeqBusy  = 0x101u * 4u;
constexpr uint32_t kCxMiscTcmRet = 0x39u * 4u;
constexpr uint32_t kAoIrqClr     = kGmuReg(0x23b04);
constexpr uint32_t kAoIrqMask    = kGmuReg(0x23b06);
constexpr uint32_t kAoFatal      = (1u << 0) | (1u << 3) | (1u << 5);
constexpr uint32_t kG2hClr       = kGmuReg(0x1f991);
constexpr uint32_t kG2hInfo      = kGmuReg(0x1f992);
constexpr uint32_t kG2hMask      = kGmuReg(0x1f993);
constexpr uint32_t kH2gSet       = kGmuReg(0x1f994);
constexpr uint32_t kGxStatus     = kGmuReg(0x1f8d0);

// Heap-allocated runtime state (keeps __DATA tiny!)
struct GpuState {
    OSSharedPtr<IOMemoryMap> maps[5];
    uintptr_t va[5]{};
    OSSharedPtr<IOMemoryMap> smmuMap;
    OSSharedPtr<IOMemoryMap> coldMaps[5];
    OSSharedPtr<IOMemoryMap> payloadMaps[5];
    OSSharedPtr<IOMemoryMap> gpuMaps[GpuBufferCount];
    volatile uint8_t *gpuCpu[GpuBufferCount]{};
    NativeAdrenoGpuBuffer gpuBuffers[GpuBufferCount]{};
    ShengGmuMmio coldMmio{};
    ShengGmuDevice coldDevice{};
    ShengGmuConfig coldConfig{};
    ShengGmuStartupResult coldResult{};
    ShengGmuVoteInputs voteInputs{};
    AdrenoHfiStartupConfig startup{};
    NativeAdrenoGmuContextReport gmuCtx{};
    NativeAdrenoGmuContextReport gpuCtx{};
    NativeAdrenoRing ring;
    NativeAdrenoCpInit cpInit;
    NativeAdrenoSubmit submit;
    NativeAdrenoTimer timer;
    NativeAdrenoMemory zapMeta;
    NativeAdrenoAbiDeviceInfo devInfo{
        kChipIdA730,
        2u << 20,              /* A730 GMEM = 2 MiB */
        0ULL,                  /* A730 MSM_PARAM_GMEM_BASE = 0 */
        0x1fffffffff000ULL,    /* UCHE_TRAP_BASE */
        GpuClientVaStart,
        0ULL,                  /* va_size populated from SMMU IAS */
        16u,                   /* highest_bank_bit (sm8350_data / sm8475) */
        6u,                    /* ubwc_swizzle = LVL2 | LVL3 */
        1u,                    /* macrotile_mode = true (8-channel) */
        4u,                    /* UBWC_4_0 */
        NativeAdrenoDeviceClientIova,
        0u
    };
    uint8_t *cmdDb = nullptr;
    uint32_t perfVote[2]{};
    bool zapLoaded = false;
    volatile bool irqAttached = false;
    volatile uint32_t irqCount = 0;
    volatile uint32_t irqSeen = 0;
    volatile uint32_t irqEmpty = 0;
    unsigned pauseUs = 1000;
};

GpuState *gS = nullptr;

void usbFlush(unsigned maxMs = 4000) {
    uint64_t target = liuqin_debug_total();
    unsigned waited = 0;
    while (liuqin_r102_usb_completed() < target && waited < maxMs) {
        IOSleep(10);
        waited += 10;
    }
    IOSleep(30);
}

void delayUs(void *, unsigned us) { IODelay(us); }

int gpbRd(void *, unsigned w, uint32_t off, uint32_t *out) {
    if (!gS || w > 4 || !gS->va[w] || off >= kLen[w] || (off & 3u)) return -1;
    *out = *reinterpret_cast<volatile uint32_t *>(gS->va[w] + off);
    return 0;
}

int gpbWr(void *, unsigned w, uint32_t off, uint32_t val) {
    if (!gS || w > 4 || !gS->va[w] || off >= kLen[w] || (off & 3u)) return -1;
    *reinterpret_cast<volatile uint32_t *>(gS->va[w] + off) = val;
    __asm__ volatile("dsb sy" ::: "memory");
    return 0;
}

int coldSha256(void *, const void *data, size_t bytes, uint8_t digest[32]) {
    if (!data || !bytes || !digest) return 1;
    SHA256_CTX ctx;
    SHA256_Init(&ctx);
    SHA256_Update(&ctx, data, bytes);
    SHA256_Final(digest, &ctx);
    return 0;
}

int coldNow(void *, uint64_t *us) {
    uint64_t ns = 0;
    absolutetime_to_nanoseconds(mach_absolute_time(), &ns);
    *us = ns / 1000ULL;
    return 0;
}

int coldWait(void *, unsigned us) { IODelay(us); return 0; }
int hfiWait(void *) { IODelay(100); return 0; }

uint32_t gpuRd(uint32_t reg) {
    uint32_t v = 0xdeadbeefu;
    gS->coldDevice.io.read32(gS->coldDevice.io.cookie, ShengGmuGpu, size_t(reg) * 4u, &v);
    return v;
}
void gpuWr(uint32_t reg, uint32_t val) {
    gS->coldDevice.io.write32(gS->coldDevice.io.cookie, ShengGmuGpu, size_t(reg) * 4u, val);
}
void gpuWr64(uint32_t reg, uint64_t val) {
    gpuWr(reg, uint32_t(val));
    gpuWr(reg + 1u, uint32_t(val >> 32));
}
void gmuWr(uint32_t dword, uint32_t val) {
    gS->coldDevice.io.write32(gS->coldDevice.io.cookie, ShengGmuCore, kGmuReg(dword), val);
}
uint32_t gmuRd(uint32_t dword) {
    uint32_t v = 0xdeadbeefu;
    gS->coldDevice.io.read32(gS->coldDevice.io.cookie, ShengGmuCore, kGmuReg(dword), &v);
    return v;
}
bool gxOn() {
    uint32_t v = 3u;
    gS->coldDevice.io.read32(gS->coldDevice.io.cookie, ShengGmuCore, kGxStatus, &v);
    return !(v & 3u);
}

int ringWrite(void *, uint32_t reg, uint32_t val) {
    return gS->coldDevice.io.write32(gS->coldDevice.io.cookie, ShengGmuGpu, size_t(reg) * 4u, val);
}
int ringRead(void *, uint32_t reg, uint32_t *val) {
    return gS->coldDevice.io.read32(gS->coldDevice.io.cookie, ShengGmuGpu, size_t(reg) * 4u, val);
}
int ringBarrier(void *) { __asm__ volatile("dsb sy" ::: "memory"); return 0; }
int ringPublish(void *, const volatile uint32_t *, size_t) { __asm__ volatile("dsb sy" ::: "memory"); return 0; }
int ringAcquire(void *, volatile uint32_t *, size_t) { __asm__ volatile("dsb sy" ::: "memory"); return 0; }
uint64_t ringNow(void *) { uint64_t us = 0; coldNow(nullptr, &us); return us; }

int ringIdle(void *) {
    if (gS && gS->irqAttached && ml_get_interrupts_enabled() && !ml_at_interrupt_context() && get_preemption_level() == 0) {
        assert_wait_timeout(event_t(&gS->irqCount), THREAD_UNINT, gS->pauseUs, NSEC_PER_USEC);
        (void)thread_block(THREAD_CONTINUE_NULL);
    } else {
        IODelay(20);
    }
    return 0;
}

uint32_t gpuFsr() {
    const uint32_t id1 = gS->gpuCtx.id1;
    if (!gS->smmuMap || !id1) return 0xdeadu;
    const size_t page = (id1 >> 31) ? 0x10000u : 0x1000u;
    const size_t bank0 = page << (((id1 >> 28) & 7u) + 1u);
    if (bank0 + 0x60u > kSmmuWindow) return 0xdeadu;
    return *reinterpret_cast<volatile uint32_t *>(gS->smmuMap->getVirtualAddress() + bank0 + 0x58u);
}

void gpuSetActlr() {
    const uint32_t id1 = gS->gpuCtx.id1;
    if (!gS->smmuMap || !id1) return;
    const size_t page = (id1 >> 31) ? 0x10000u : 0x1000u;
    const size_t bank0 = page << (((id1 >> 28) & 7u) + 1u);
    if (bank0 + 0x800u > kSmmuWindow) return;
    volatile uint32_t *base = reinterpret_cast<volatile uint32_t *>(gS->smmuMap->getVirtualAddress());
    uint32_t before = base[(bank0 + 0x4u) / 4u];
    base[(bank0 + 0x4u) / 4u] = 0x301u;
    __asm__ volatile("dsb sy" ::: "memory");
    base[(bank0 + 0x618u) / 4u] = 0;
    base[(bank0 + 0x7f0u) / 4u] = 0;
    for (unsigned i = 0; i < 1000 && (base[(bank0 + 0x7f4u) / 4u] & 1u); ++i) IODelay(1);
    uint32_t after = base[(bank0 + 0x4u) / 4u];
    IOLog("LQ102GPU ACTLR before=0x%x after=0x%x\n", before, after);
}

bool physRead64(uint64_t pa, uint64_t *out) {
    const vm_offset_t va = ml_io_map_unmappable(vm_offset_t(pa & ~uint64_t(0xfff)), 0x1000, 0x7);
    if (!va) return false;
    *out = *reinterpret_cast<volatile uint64_t *>(va + (pa & 0xff8u));
    ml_io_unmap(va, 0x1000);
    return true;
}

int dramRead32(uint64_t pa, uint32_t *value) {
    uint64_t w = 0;
    if (!physRead64(pa & ~uint64_t(7), &w)) return 1;
    *value = uint32_t(w >> ((pa & 4u) * 8u));
    return 0;
}

int cachedRead32(uint64_t pa, uint32_t *value) {
    if ((pa & 3u) || pa < gPhysBase || pa - gPhysBase >= gPhysSize) return 1;
    const vm_offset_t va = phystokv(pa);
    if (!va) return 1;
    *value = *reinterpret_cast<volatile uint32_t *>(va);
    __asm__ volatile("dsb sy\n\tdc civac, %0\n\tdsb sy" :: "r"(va) : "memory");
    return 0;
}

int lineAudit(uint64_t pa, size_t bytes, uint32_t *dirty, uint32_t *stale) {
    if (!bytes || ((pa | bytes) & 63u) || (pa & 0xfffu) + bytes > 0x1000u || pa < gPhysBase || pa - gPhysBase >= gPhysSize)
        return 1;
    const vm_offset_t page = ml_io_map_unmappable(vm_offset_t(pa & ~uint64_t(0xfff)), 0x1000, 0x7);
    const vm_offset_t cached = phystokv(pa);
    if (!page || !cached) { if (page) ml_io_unmap(page, 0x1000); return 1; }
    const vm_offset_t dram = page + vm_offset_t(pa & 0xfffu);
    for (size_t at = 0; at < bytes; at += 64) {
        const volatile uint64_t *c = reinterpret_cast<const volatile uint64_t *>(cached + at);
        const volatile uint64_t *d = reinterpret_cast<const volatile uint64_t *>(dram + at);
        uint64_t copy[8];
        bool differs = false;
        for (unsigned i = 0; i < 8; ++i) { copy[i] = c[i]; if (copy[i] != d[i]) differs = true; }
        if (!differs) continue;
        __asm__ volatile("dsb sy\n\tdc civac, %0\n\tdsb sy" :: "r"(cached + at) : "memory");
        bool written = true;
        for (unsigned i = 0; i < 8; ++i) if (d[i] != copy[i]) written = false;
        if (written) ++*dirty; else ++*stale;
    }
    ml_io_unmap(page, 0x1000);
    return 0;
}

bool dramPage(uint64_t pa, uint32_t *out) {
    const vm_offset_t page = ml_io_map_unmappable(vm_offset_t(pa), 0x1000, 0x7);
    if (!page) return false;
    for (unsigned i = 0; i < 1024; ++i) out[i] = reinterpret_cast<const volatile uint32_t *>(page)[i];
    ml_io_unmap(page, 0x1000);
    return true;
}

bool cpFence(const uint32_t *words, size_t count) {
    uint32_t fence = 0, seen = 0;
    if (gS->ring.submit(words, count, &fence)) return false;
    const NativeAdrenoRingClock clock{nullptr, ringNow, ringIdle};
    return gS->ring.wait(fence, &clock, 200000, &seen) == NativeAdrenoRingFenceComplete;
}

bool gpuCopyPage(uint64_t src, uint64_t dst) {
    uint32_t words[8] = {};
    if (AdrenoPM4Type7(0x75, 5, &words[0]) != AdrenoPM4Success ||
        AdrenoPM4Type7(0x12, 0, &words[6]) != AdrenoPM4Success)
        return false;
    words[1] = 1024;
    words[2] = uint32_t(src); words[3] = uint32_t(src >> 32);
    words[4] = uint32_t(dst); words[5] = uint32_t(dst >> 32);
    return cpFence(words, 7);
}

struct ScmRes { int64_t a0; uint64_t a1; uint32_t ms, resumes; };

ScmRes scmCall(uint64_t fn, uint64_t arginfo, uint64_t p0, uint64_t p1, uint64_t p2, uint64_t p3 = 0) {
    uint64_t first = fn, a6 = 0;
    const uint64_t start = ringNow(nullptr);
    auto done = [&](int64_t a0, uint64_t a1, unsigned resumes) {
        return ScmRes{a0, a1, uint32_t((ringNow(nullptr) - start) / 1000ULL), resumes};
    };
    for (unsigned resume = 0, busy = 0; resume < 10000;) {
        register uint64_t x0 asm("x0") = first, x1 asm("x1") = arginfo, x2 asm("x2") = p0, x3 asm("x3") = p1;
        register uint64_t x4 asm("x4") = p2, x5 asm("x5") = p3, x6 asm("x6") = a6, x7 asm("x7") = 0;
        asm volatile("smc #0"
                     : "+r"(x0), "+r"(x1), "+r"(x2), "+r"(x3), "+r"(x4), "+r"(x5), "+r"(x6), "+r"(x7)
                     :: "x8", "x9", "x10", "x11", "x12", "x13", "x14", "x15", "x16", "x17", "memory");
        if (x0 == 1) { first = 1; a6 = x6; ++resume; continue; }
        if (int64_t(x0) == -12 && busy++ < 20) { first = fn; a6 = 0; IOSleep(30); continue; }
        return done(int64_t(x0), x1, resume);
    }
    return done(-1000, 0, 10000);
}

constexpr uint64_t kScmPil(uint32_t cmd) { return 0x42000000ULL | (0x02ULL << 8) | cmd; }
uint32_t rd32le(const uint8_t *p) { return uint32_t(p[0]) | (uint32_t(p[1]) << 8) | (uint32_t(p[2]) << 16) | (uint32_t(p[3]) << 24); }
uint16_t rd16le(const uint8_t *p) { return uint16_t(p[0] | (uint16_t(p[1]) << 8)); }

void gpuHwInit() {
    gpuWr(A740_GBIF_HALT, 0); (void)gpuRd(A740_GBIF_HALT);
    gpuWr(A740_RBBM_GBIF_HALT, 0); (void)gpuRd(A740_RBBM_GBIF_HALT);
    gpuWr(A740_RBBM_SECVID_TSB_CNTL, 0);
    gpuWr64(A740_RBBM_SECVID_TSB_TRUSTED_BASE, 0);
    gpuWr(A740_RBBM_SECVID_TSB_TRUSTED_SIZE, 0);

    // A730 HWCG: gmu_cgc_mode = 0x00020000, a730_hwcg (53 entries)
    gmuWr(A740_GPU_GMU_AO_GMU_CGC_MODE_CNTL, LIUQIN_A730_GMU_CGC_MODE);
    gmuWr(A740_GPU_GMU_AO_GMU_CGC_DELAY_CNTL, 0x10111u);
    gmuWr(A740_GPU_GMU_AO_GMU_CGC_HYST_CNTL, 0x5555u);
    if (gpuRd(A740_RBBM_CLOCK_CNTL) != 0x8aa8aa82u) {
        for (unsigned i = 0; i < LIUQIN_A730_HWCG_COUNT; ++i)
            gpuWr(LiuqinA730Hwcg[i][0], LiuqinA730Hwcg[i][1]);
        gpuWr(A740_RBBM_CLOCK_CNTL, 0x8aa8aa82u);
    }

    gpuWr(0x3c03u, 0x00071620u); /* GBIF_QSB_SIDE0 (a6xx_gpu.c:1132, after GX ON) */
    gpuWr(0x3c04u, 0x00071620u); /* GBIF_QSB_SIDE1 */
    gpuWr(0x3c05u, 0x00071620u); /* GBIF_QSB_SIDE2 */
    gpuWr(0x3c06u, 0x00071620u); /* GBIF_QSB_SIDE3 */
    gpuWr(A740_RBBM_GBIF_CLIENT_QOS_CNTL, 0x2120212u);
    gpuWr(A740_UCHE_GBIF_GX_CONFIG, 0x10240e0u);
    gpuWr(A740_RBBM_PERFCTR_GPU_BUSY_MASKED, 0xffffffffu);
    gpuWr64(A740_UCHE_TRAP_BASE, 0x1fffffffff000ULL);
    gpuWr64(A740_UCHE_WRITE_THRU_BASE, 0x1fffffffff000ULL);
    // A730 skips UCHE_GMEM_RANGE_MIN / MAX per a6xx_gpu.c:1161-1171!
    gpuWr(A740_UCHE_CACHE_WAYS, 1u << 23);
    gpuWr(A740_CP_AHB_CNTL, 0x1u);
    gpuWr(A740_RBBM_PERFCTR_CNTL, 0x1u);
    gpuWr(A740_RBBM_INTERFACE_HANG_INT_CNTL, (1u << 30) | 0xcfffffu);
    gpuWr(A740_UCHE_CLIENT_PF, (1u << 7) | 0x1u);

    // CP protect: a730_protect (identical to NativeAdrenoA740Protect)
    gpuWr(A740_CP_PROTECT_CNTL, (1u << 0) | (1u << 1) | (1u << 3));
    for (unsigned i = 0; i < NATIVE_ADRENO_A740_PROTECT_COUNT; ++i)
        gpuWr(A740_CP_PROTECT + NativeAdrenoA740Protect[i][0], NativeAdrenoA740Protect[i][1]);

    gpuWr(A740_UCHE_CMDQ_CONFIG, (6u << 16) | (6u << 12) | (9u << 8) | (1u << 3) | (1u << 2) | 2u);
    gpuWr(A740_CP_APRIV_CNTL, 0x6fu);
    gpuWr(A740_CP_BV_APRIV_CNTL, 0x0fu);
    gpuWr(A740_CP_LPAC_APRIV_CNTL, 0x0fu);
    gpuWr(A740_RB_CMP_DBG_ECO_CNTL, gpuRd(A740_RB_CMP_DBG_ECO_CNTL) | (1u << 11));

    // UBWC config (sm8350_data for qcom,sm8475: UBWC 4.0 enc, LVL2+LVL3, hbb=16 -> hbb_lo=3, macrotile=1)
    gpuWr(A740_RB_NC_MODE_CNTL, (1u << 11) | (1u << 4) | (3u << 1));
    gpuWr(A740_TPL1_NC_MODE_CNTL, 3u << 1);
    gpuWr(A740_SP_NC_MODE_CNTL, (2u << 4) | (3u << 1));
    for (uint32_t pipe = 1; pipe <= 2; ++pipe) {
        gpuWr(A740_CP_APERTURE_CNTL_HOST, pipe << 12);
        gpuWr(A740_GRAS_NC_MODE_CNTL, 3u << 5);
    }
    gpuWr(A740_CP_APERTURE_CNTL_HOST, 0);
    gpuWr(A740_UCHE_MODE_CNTL, 3u << 21);
    gpuWr(A740_RBBM_NC_MODE_CNTL, 1u);

    gpuWr(A740_RBBM_INT_0_MASK, 0x33d283c2u);
    gpuWr64(A740_CP_SQE_INSTR_BASE, gS->gpuBuffers[0].iova);
}

IOReturn gpuRestart(void *, NativeAdrenoRing *ring, uint32_t completed) {
    if (!ring) return kIOReturnBadArgument;
    static uint32_t hangLogCount = 0;
    if (hangLogCount < 5) {
        ++hangLogCount;
        uint32_t ss[NativeAdrenoRingStallWords] = {};
        if (gxOn()) (void)ring->stallState(ss);
        uint32_t smmuFsr = 0, smmuFsynr0 = 0, smmuSctlr = 0;
        uint64_t smmuFar = 0, smmuTtbr0 = 0;
        const uint32_t id1 = gS->gpuCtx.id1;
        if (gS->smmuMap && id1) {
            const size_t page = (id1 >> 31) ? 0x10000u : 0x1000u;
            const size_t bank0 = page << (((id1 >> 28) & 7u) + 1u);
            if (bank0 + 0x70u <= kSmmuWindow) {
                volatile uint32_t *b = reinterpret_cast<volatile uint32_t *>(gS->smmuMap->getVirtualAddress() + bank0);
                smmuSctlr = b[0x00 / 4];
                smmuTtbr0 = uint64_t(b[0x20 / 4]) | (uint64_t(b[0x24 / 4]) << 32);
                smmuFsr = b[0x58 / 4];
                smmuFar = uint64_t(b[0x60 / 4]) | (uint64_t(b[0x64 / 4]) << 32);
                smmuFsynr0 = b[0x68 / 4];
            }
        }
        IOLog("LQ102GPU HANG#%u comp=%u rbbm=%x/%x/%x/%x int0=%x hwflt=%x cpst1=%x prot=%x rptr=%u wptr=%u bv_rptr=%u\n",
              hangLogCount, completed, ss[0], ss[1], ss[2], ss[3], ss[4], ss[5], ss[6], ss[7], ss[8], ss[9], ss[16]);
        IOLog("LQ102GPU HANG#%u ib1=%x:%x/%u ib2=%x:%x/%u bv_ib1=%x/%u smmu(sctlr=%x ttbr0=%llx fsr=%x far=%llx fsynr0=%x) recflt=%u/%x/%x/%x/%x tbl=%u/%u/%x/%u\n",
              hangLogCount, ss[11], ss[10], ss[12], ss[14], ss[13], ss[15], ss[17], ss[18],
              smmuSctlr, (unsigned long long)smmuTtbr0, smmuFsr, (unsigned long long)smmuFar, smmuFsynr0,
              native_adreno_recovery_fault[0], native_adreno_recovery_fault[1], native_adreno_recovery_fault[2],
              native_adreno_recovery_fault[3], native_adreno_recovery_fault[4],
              native_adreno_table_switches[0], native_adreno_table_switches[1],
              native_adreno_table_switches[6], native_adreno_table_switches[7]);
        uint32_t bvProt = 0, bvHwFlt = 0, cpInt = 0, brPc = 0, bvPc = 0, brSt1 = 0, bvSt1 = 0;
        if (gxOn()) {
            bvProt = gpuRd(0x0a61u);
            bvHwFlt = gpuRd(0x0a64u);
            cpInt = gpuRd(0x0823u);
            gpuWr(0x0908u, 0); brPc = gpuRd(0x0909u);
            gpuWr(0x0908u, 1); brSt1 = gpuRd(0x0909u);
            gpuWr(0x0a87u, 0); bvPc = gpuRd(0x0a88u);
            gpuWr(0x0a87u, 1); bvSt1 = gpuRd(0x0a88u);
        }
        const volatile uint32_t *mp = reinterpret_cast<const volatile uint32_t *>(gS->gpuCpu[2]);
        IOLog("LQ102GPU HANG#%u bv(prot=%x hwflt=%x pc=%x/%x) br(cpint=%x pc=%x/%x) memptrs=%u,%u,%u,%u\n",
              hangLogCount, bvProt, bvHwFlt, bvPc, bvSt1, cpInt, brPc, brSt1, mp[0], mp[1], mp[2], mp[3]);
        // On HANG#1, dump ring words before rptr and translate+dump ib1 words via smmuTtbr0
        if (hangLogCount == 1 && smmuTtbr0) {
            const volatile uint32_t *rb = reinterpret_cast<const volatile uint32_t *>(gS->gpuCpu[1]);
            const uint32_t rmask = uint32_t(gS->gpuBuffers[1].bytes / 4u - 1u);
            uint32_t r0 = (ss[8] >= 12) ? (ss[8] - 12) : 0;
            IOLog("LQ102GPU HANG#1 ring[%u..]: %08x %08x %08x %08x %08x %08x %08x %08x %08x %08x %08x %08x\n",
                  r0, rb[(r0+0)&rmask], rb[(r0+1)&rmask], rb[(r0+2)&rmask], rb[(r0+3)&rmask],
                  rb[(r0+4)&rmask], rb[(r0+5)&rmask], rb[(r0+6)&rmask], rb[(r0+7)&rmask],
                  rb[(r0+8)&rmask], rb[(r0+9)&rmask], rb[(r0+10)&rmask], rb[(r0+11)&rmask]);
            uint64_t ibVa = 0; uint32_t ibDw = 0;
            if (ring->ibBefore(ss[8], &ibVa, &ibDw) == kIOReturnSuccess && ibVa) {
                uint64_t pt = smmuTtbr0 & 0xfffffffff000ULL;
                uint64_t pte = 0;
                bool ok = true;
                for (int lvl = 0; lvl < 4 && ok; ++lvl) {
                    uint64_t idx = (ibVa >> (39 - lvl * 9)) & 0x1ffULL;
                    ok = physRead64(pt + idx * 8ULL, &pte) && (pte & 1ULL);
                    if (lvl < 3) { ok = ok && (pte & 2ULL); pt = pte & 0xfffffffff000ULL; }
                }
                IOLog("LQ102GPU HANG#1 ib1_info va=0x%llx dw=%u walk_ok=%u pte=0x%llx\n",
                      (unsigned long long)ibVa, ibDw, ok ? 1u : 0u, (unsigned long long)pte);
                if (ok) {
                    uint64_t ibPa = (pte & 0xfffffffff000ULL) | (ibVa & 0xfffULL);
                    uint32_t hD[8] = {}, hC[8] = {};
                    for (unsigned k = 0; k < 8 && k < ibDw; ++k) {
                        uint64_t a = ibPa + uint64_t(k) * 4ULL;
                        if ((a >> 12) == (ibPa >> 12)) { (void)dramRead32(a, &hD[k]); (void)cachedRead32(a, &hC[k]); }
                    }
                    IOLog("LQ102GPU HANG#1 ib1_dram[0..7]: %08x %08x %08x %08x %08x %08x %08x %08x\n",
                          hD[0],hD[1],hD[2],hD[3],hD[4],hD[5],hD[6],hD[7]);
                    IOLog("LQ102GPU HANG#1 ib1_cach[0..7]: %08x %08x %08x %08x %08x %08x %08x %08x\n",
                          hC[0],hC[1],hC[2],hC[3],hC[4],hC[5],hC[6],hC[7]);
                    const uint32_t s0 = (native_adreno_ib_log_count ? (native_adreno_ib_log_count - 1) : 0) & 3u;
                    IOLog("LQ102GPU HANG#1 iblog(n=%u f=%u sz=%u): %08x %08x %08x %08x %08x %08x %08x %08x wca=%u,%u,%u,%u,%x,%u coh=%u,%x,%x,%x\n",
                          native_adreno_ib_log_count, native_adreno_ib_log[s0][0], native_adreno_ib_log[s0][3],
                          native_adreno_ib_log[s0][4], native_adreno_ib_log[s0][5], native_adreno_ib_log[s0][6], native_adreno_ib_log[s0][7],
                          native_adreno_ib_log[s0][8], native_adreno_ib_log[s0][9], native_adreno_ib_log[s0][10], native_adreno_ib_log[s0][11],
                          native_adreno_wc_audit[0], native_adreno_wc_audit[1], native_adreno_wc_audit[2],
                          native_adreno_wc_audit[3], native_adreno_wc_audit[4], native_adreno_wc_audit[5],
                          native_adreno_coherence[0], native_adreno_coherence[1], native_adreno_coherence[2], native_adreno_coherence[3]);
                    uint32_t curDw = (ibDw > ss[18]) ? (ibDw - ss[18]) : 0;
                    uint32_t dumpOff = (curDw > 8) ? (curDw - 8) : 0;
                    uint32_t w[16] = {};
                    for (unsigned k = 0; k < 16 && (dumpOff + k) < ibDw; ++k) {
                        uint64_t a = ibPa + uint64_t(dumpOff + k) * 4ULL;
                        if ((a >> 12) == (ibPa >> 12)) (void)dramRead32(a, &w[k]);
                    }
                    IOLog("LQ102GPU HANG#1 ib1[%u/%u]: %08x %08x %08x %08x %08x %08x %08x %08x | %08x %08x %08x %08x %08x %08x %08x %08x\n",
                          curDw, ibDw, w[0],w[1],w[2],w[3],w[4],w[5],w[6],w[7],w[8],w[9],w[10],w[11],w[12],w[13],w[14],w[15]);
                }
            }
        }
    }
    if (gxOn()) gpuWr(A740_CP_SQE_CNTL, 3u);
    IOReturn st = ring->busHalt(true, 1000000);
    if (st) return st;
    gpuWr(A740_RBBM_SW_RESET_CMD, 1u); (void)gpuRd(A740_RBBM_SW_RESET_CMD); IODelay(100);
    gpuWr(A740_RBBM_SW_RESET_CMD, 0u); (void)gpuRd(A740_RBBM_SW_RESET_CMD); IODelay(1);
    gpuHwInit();
    st = ring->restart(completed);
    if (st) return st;
    gpuWr64(A740_CP_BV_RB_RPTR_ADDR, gS->gpuBuffers[2].iova + 8u);
    gpuWr(A740_CP_SQE_CNTL, 1u);
    const NativeAdrenoRingIo rio{nullptr, ringWrite, ringRead, ringBarrier, nullptr, nullptr};
    const NativeAdrenoCpInitConfig cfg{gS->gpuBuffers[0].iova, gS->gpuBuffers[3].iova, 1};
    const NativeAdrenoRingClock clock{nullptr, ringNow, nullptr};
    NativeAdrenoCpInit init;
    uint32_t fence = 0;
    st = init.run(&rio, ring, &cfg, &fence, false);
    if (st) return st;
    st = ring->idle(&clock, 1000000);
    if (st) return st;
    if (gS->zapLoaded) {
        uint32_t words[2] = {};
        if (AdrenoPM4Type7(0x66, 1, &words[0]) != AdrenoPM4Success) return kIOReturnInternalError;
        st = ring->submitUnfenced(words, 2);
        if (!st) st = ring->idle(&clock, 1000000);
        if (st) return st;
    }
    return kIOReturnSuccess;
}

void gpuIrq(void *) {
    const uint32_t status = gpuRd(A740_RBBM_INT_0_STATUS);
    if (status) gpuWr(A740_RBBM_INT_CLEAR_CMD, status);
    gS->irqSeen = gS->irqSeen | status;
    gS->irqCount = gS->irqCount + 1u;
    gS->irqEmpty = status ? 0u : (gS->irqEmpty + 1u);
    if (gS->irqEmpty > 100000u) gpuWr(A740_RBBM_INT_0_MASK, 0u);
    thread_wakeup(event_t(&gS->irqCount));
}

bool loadZapAndLeaveSecureMode() {
    const uint8_t *fw = native_adreno_zap_image;
    const uint64_t size = native_adreno_zap_image_size;
    IOLog("LQ102GPU ZAP_BEGIN bytes=%llu phys=0x%llx/0x%llx\n",
          (unsigned long long)size, (unsigned long long)kZapPhys, (unsigned long long)kZapBytes);
    usbFlush();

    if (size < 52 || fw[0] != 0x7f || fw[1] != 'E' || fw[2] != 'L' || fw[3] != 'F' || fw[4] != 1) {
        IOLog("LQ102GPU ZAP_ERR stage=elf_hdr\n");
        return false;
    }
    const uint32_t phoff = rd32le(fw + 28);
    const unsigned phent = rd16le(fw + 42), phnum = rd16le(fw + 44);
    if (phent != 32 || phnum < 2 || phnum > 16 || phoff + uint64_t(phnum) * 32 > size) {
        IOLog("LQ102GPU ZAP_ERR stage=phdr phent=%u phnum=%u\n", phent, phnum);
        return false;
    }
    auto ph = [&](unsigned i, unsigned field) { return rd32le(fw + phoff + i * 32u + field * 4u); };
    if (ph(0, 0) == 1) { IOLog("LQ102GPU ZAP_ERR stage=ph0_load\n"); return false; }
    unsigned hash = 0;
    for (unsigned i = 1; i < phnum && !hash; ++i)
        if (((ph(i, 6) >> 24) & 7u) == 2u) hash = i;
    if (!hash) { IOLog("LQ102GPU ZAP_ERR stage=no_hash\n"); return false; }

    uint64_t lo = ~0ULL, hi = 0;
    bool relocate = false;
    for (unsigned i = 0; i < phnum; ++i) {
        if (ph(i, 0) != 1 || ((ph(i, 6) >> 24) & 7u) == 2u || !ph(i, 5)) continue;
        if (ph(i, 6) & (1u << 27)) relocate = true;
        lo = lo < ph(i, 3) ? lo : ph(i, 3);
        const uint64_t end = (uint64_t(ph(i, 3)) + ph(i, 5) + 0xfffULL) & ~0xfffULL;
        hi = hi > end ? hi : end;
    }
    if (lo >= hi || hi - lo > kZapBytes) {
        IOLog("LQ102GPU ZAP_ERR stage=range lo=0x%llx hi=0x%llx\n", (unsigned long long)lo, (unsigned long long)hi);
        return false;
    }
    const uint64_t ehdr = ph(0, 4), hashBytes = ph(hash, 4), hashOff = ph(hash, 1);
    if (ehdr > size || hashOff + hashBytes > size || ehdr + hashBytes > 0x4000ULL) {
        IOLog("LQ102GPU ZAP_ERR stage=meta_bounds\n");
        return false;
    }
    const size_t metaBytes = size_t((ehdr + hashBytes + 0xfffULL) & ~0xfffULL);
    if (gS->zapMeta.allocate(metaBytes, 40, true, metaBytes) || gS->zapMeta.spanCount() != 1) {
        IOLog("LQ102GPU ZAP_ERR stage=meta_alloc\n");
        return false;
    }
    uint8_t *meta = static_cast<uint8_t *>(gS->zapMeta.mapping());
    memcpy(meta, fw, size_t(ehdr));
    memcpy(meta + ehdr, fw + hashOff, size_t(hashBytes));
    if (gS->zapMeta.publishForDevice(0, metaBytes, true)) {
        IOLog("LQ102GPU ZAP_ERR stage=meta_pub\n");
        return false;
    }

    // Check PAS call availability first (FAST call 0xc2000601 verified in r102-p12)
    ScmRes av = scmCall(0xc2000601ULL, 1, 0x02000201ULL, 0, 0);
    IOLog("LQ102GPU ZAP_AVAIL init_x0=%lld x1=0x%llx relocate=%u span=0x%llx\n",
          (long long)av.a0, (unsigned long long)av.a1, relocate ? 1u : 0u, (unsigned long long)(hi - lo));
    usbFlush();

    ScmRes r = scmCall(kScmPil(0x01), 2u | (2u << 6), kGpuPasId, gS->zapMeta.spans()[0].physical, 0);
    IOLog("LQ102GPU ZAP_INIT a0=%lld a1=0x%llx ms=%u res=%u\n",
          (long long)r.a0, (unsigned long long)r.a1, r.ms, r.resumes);
    usbFlush();
    if (r.a0 || r.a1) return false;

    if (relocate) {
        r = scmCall(kScmPil(0x02), 3u, kGpuPasId, kZapPhys, hi - lo);
        IOLog("LQ102GPU ZAP_MEMSETUP a0=%lld a1=0x%llx ms=%u res=%u\n",
              (long long)r.a0, (unsigned long long)r.a1, r.ms, r.resumes);
        usbFlush();
        if (r.a0 || r.a1) return false;
    }

    {
        IODeviceMemory *m = IODeviceMemory::withRange(kZapPhys, kZapBytes);
        OSSharedPtr<IOMemoryMap> map;
        if (m) {
            map = OSSharedPtr<IOMemoryMap>(m->map(kIOMapAnywhere | kIOMapWriteCombineCache), OSNoRetain);
            m->release();
        }
        if (!map) { IOLog("LQ102GPU ZAP_ERR stage=map_region\n"); return false; }
        volatile uint8_t *region = reinterpret_cast<volatile uint8_t *>(map->getVirtualAddress());
        const uint64_t base = relocate ? lo : kZapPhys;
        for (unsigned i = 0; i < phnum; ++i) {
            if (ph(i, 0) != 1 || ((ph(i, 6) >> 24) & 7u) == 2u || !ph(i, 5)) continue;
            const uint64_t at = uint64_t(ph(i, 3)) - base, file = ph(i, 4), mem = ph(i, 5), off = ph(i, 1);
            if (ph(i, 3) < base || at + mem > kZapBytes || file > mem || off + file > size) {
                IOLog("LQ102GPU ZAP_ERR stage=seg_copy\n");
                return false;
            }
            for (uint64_t b = 0; b < file; ++b) region[at + b] = fw[off + b];
            for (uint64_t b = file; b < mem; ++b) region[at + b] = 0;
        }
        __asm__ volatile("dsb sy" ::: "memory");
    }

    r = scmCall(kScmPil(0x05), 1u, kGpuPasId, 0, 0);
    IOLog("LQ102GPU ZAP_AUTH a0=%lld a1=0x%llx ms=%u res=%u\n",
          (long long)r.a0, (unsigned long long)r.a1, r.ms, r.resumes);
    usbFlush();
    if (r.a0 || r.a1) return false;

    uint32_t words[2] = {};
    uint32_t fence = 0, seen = 0;
    if (AdrenoPM4Type7(0x66, 1, &words[0]) != AdrenoPM4Success || gS->ring.submit(words, 2, &fence)) {
        IOLog("LQ102GPU ZAP_ERR stage=sec_submit\n");
        return false;
    }
    const NativeAdrenoRingClock clock{nullptr, ringNow, ringIdle};
    NativeAdrenoRingFence wf = gS->ring.wait(fence, &clock, 200000, &seen);
    IOLog("LQ102GPU ZAP_SECMODE_EXIT wait=%u fence=%u seen=%u\n", unsigned(wf), fence, seen);
    usbFlush();
    if (wf != NativeAdrenoRingFenceComplete) return false;
    gS->zapLoaded = true;
    return true;
}

void openCpAperture() {
    const ScmRes avail = scmCall(0xc2000601ULL, 1, 0x02000000ULL | (0x0cULL << 8) | 0x1bULL, 0, 0);
    native_adreno_cp_aperture[0] = avail.a0 ? (0x80000000u | uint32_t(avail.a0)) : uint32_t(avail.a1);
    if (avail.a0 || !avail.a1) {
        native_adreno_cp_aperture[1] = 0xffffffffu;
        IOLog("LQ102GPU CP_APERTURE avail_a0=%lld a1=0x%llx\n", (long long)avail.a0, (unsigned long long)avail.a1);
        return;
    }
    const ScmRes r = scmCall(0x42000c1bULL, 4, 0xffff0000ULL, 0xffffffffULL, 0xffffffffULL, 0xffffffffULL);
    native_adreno_cp_aperture[1] = uint32_t(r.a0);
    IOLog("LQ102GPU CP_APERTURE set_a0=%lld a1=0x%llx\n", (long long)r.a0, (unsigned long long)r.a1);
}

void coherenceProbe(NativeAdrenoVm *vm) {
    constexpr uint64_t kIova = 0x18000000ULL;
    constexpr size_t kBytes = 4 * 4096;
    uint8_t *buf = static_cast<uint8_t *>(IOMallocAligned(kBytes, 4096));
    uint32_t *words = static_cast<uint32_t *>(IOMallocData(4096));
    if (!buf || !words) {
        if (buf) IOFreeAligned(buf, kBytes);
        if (words) IOFreeData(words, 4096);
        return;
    }
    NativeAdrenoMemory mem;
    uint64_t handle = 0;
    IOReturn st = mem.importTask(kernel_task, uint64_t(uintptr_t(buf)), kBytes, 40, kBytes);
    if (!st) st = vm->map(&mem, 0, kIova, 3, 1, 3, &handle);
    uint64_t phys[4] = {};
    for (size_t j = 0; !st && j < mem.spanCount(); ++j)
        for (size_t at = 0; at < mem.spans()[j].bytes; at += 4096)
            phys[(mem.spans()[j].offset + at) / 4096] = mem.spans()[j].physical + at;
    bool pass = false;
    uint32_t dirtyLines = 0, rNew = 0, wCpu = 0, wDram = 0;
    if (!st && phys[0] && phys[1] && phys[2] && phys[3]) {
        volatile uint32_t *S = reinterpret_cast<volatile uint32_t *>(buf);
        volatile uint32_t *D = S + 1024, *R = S + 2048, *T = S + 3072;
        bool dirty = false;
        for (unsigned attempt = 0; attempt < 8 && !st && !dirty; ++attempt) {
            for (unsigned i = 0; i < 1024; ++i) { S[i] = 0x11110000u | i; D[i] = 0; R[i] = 0x33330000u | i; T[i] = 0x44440000u | i; }
            st = NativeAdrenoMaintainOwnedPages(buf, kBytes, NativeAdrenoCleanInvalidate);
            for (unsigned i = 0; i < 1024; ++i) S[i] = 0x22220000u | i;
            __asm__ volatile("dsb sy" ::: "memory");
            dirtyLines = 0;
            if (!st && dramPage(phys[0], words))
                for (unsigned i = 0; i < 1024; i += 16) dirtyLines += (words[i] == (0x11110000u | i));
            dirty = dirtyLines >= 48;
        }
        if (!st && dirty && gpuCopyPage(kIova, kIova + 4096) && dramPage(phys[1], words)) {
            for (unsigned i = 0; i < 1024; ++i) rNew += (words[i] == (0x22220000u | i));
        }
        if (!st && rNew == 1024) {
            st = NativeAdrenoMaintainOwnedPages(const_cast<uint32_t *>(T), 4096, NativeAdrenoClean);
            uint32_t touch = 0;
            for (unsigned i = 0; i < 1024; ++i) touch += T[i];
            (void)touch;
            __asm__ volatile("dsb sy" ::: "memory");
            if (!st && gpuCopyPage(kIova + 8192, kIova + 12288)) {
                for (unsigned i = 0; i < 1024; ++i) wCpu += (T[i] == (0x33330000u | i));
                if (dramPage(phys[3], words))
                    for (unsigned i = 0; i < 1024; ++i) wDram += (words[i] == (0x33330000u | i));
            }
        }
        pass = (dirtyLines >= 48 && rNew == 1024 && wCpu == 1024 && wDram == 1024);
    }
    if (handle) (void)vm->unmap(handle);
    (void)NativeAdrenoMaintainOwnedPages(buf, kBytes, NativeAdrenoCleanInvalidate);
    (void)mem.release();
    IOFreeAligned(buf, kBytes);
    IOFreeData(words, 4096);
    native_adreno_io_coherent = pass ? 1u : 0u;
    if (pass) gS->devInfo.flags |= NativeAdrenoDeviceCachedCoherent;
    IOLog("LQ102GPU COHERENCE dirty=%u/64 rNew=%u wCpu=%u wDram=%u st=0x%x -> %s\n",
          dirtyLines, rNew, wCpu, wDram, unsigned(st), pass ? "on" : "off");
}

int timerRead(void *, uint32_t reg, uint32_t *val) { *val = gpuRd(reg); return 0; }
static const NativeAdrenoTimeIo kTimerIo{nullptr, timerRead};

void publishMetalAccelerator() {
    kern_return_t krc = OSKextLoadKextWithIdentifier("com.apple.iokit.IOGraphicsFamily");
    if (krc) {
        IOLog("LQ102GPU METAL_ACCEL_ERR stage=kext krc=0x%x\n", unsigned(krc));
        return;
    }
    const OSSymbol *name = OSSymbol::withCString("IOAccelerator");
    const OSMetaClass *parent = name ? OSMetaClass::getMetaClassWithName(name) : nullptr;
    OSSafeReleaseNULL(name);
    if (!parent || parent->getClassSize() != 136) {
        IOLog("LQ102GPU METAL_ACCEL_ERR stage=parent size=%u\n", parent ? parent->getClassSize() : 0u);
        return;
    }
    void *handle = OSMetaClass::preModLoad(g_kernel_kmod_info.name);
    if (!handle) { IOLog("LQ102GPU METAL_ACCEL_ERR stage=preModLoad\n"); return; }
    native_adreno_accelerator_static_init();
    kern_return_t prc = OSMetaClass::postModLoad(handle);
    if (prc) { IOLog("LQ102GPU METAL_ACCEL_ERR stage=postModLoad rc=0x%x\n", unsigned(prc)); return; }
    if (native_adreno_accelerator_instance_size() != 136) {
        IOLog("LQ102GPU METAL_ACCEL_ERR stage=size sz=%u\n", native_adreno_accelerator_instance_size());
        return;
    }
    IOService *accel = native_adreno_accelerator_allocate();
    if (!accel || !accel->init()) {
        if (accel) accel->release();
        IOLog("LQ102GPU METAL_ACCEL_ERR stage=alloc_init\n");
        return;
    }
    accel->setProperty("MetalPluginName", "NativeAdrenoMetal");
    accel->setProperty("MetalPluginClassName", "NativeAdrenoMetalDevice");
    accel->setProperty("NativeSandboxGrantProcess", "*");
    if (!accel->attach(IOService::getPlatform())) {
        accel->release();
        IOLog("LQ102GPU METAL_ACCEL_ERR stage=attach\n");
        return;
    }
    accel->registerService();
    IOLog("LQ102GPU METAL_ACCEL_OK registered=1 class=AGXAccelerator plugin=NativeAdrenoMetal\n");
}

void gpuBringupWorker(void *, wait_result_t) {
    mach_timespec_t timeout = {30, 0};
    (void)IOService::waitForService(IOService::resourceMatching("IOBSD"), &timeout);

    IOLog("LQ102GPU BEGIN chip=0x%08x fw_gmu=%llu fw_sqe=%llu fw_zap=%llu\n",
          kChipIdA730,
          (unsigned long long)native_adreno_firmware_image_size,
          (unsigned long long)native_adreno_sqe_firmware_image_size,
          (unsigned long long)native_adreno_zap_image_size);
    usbFlush();

    gS = new GpuState;
    if (!gS) { IOLog("LQ102GPU ERR oom_state\n"); return; }

    // Stage 1-3: Map GCC, GPUCC, SMMU GR0, GPU windows & power on CX GDSC + SMMU clocks
    unsigned have = 0;
    for (unsigned w = 0; w < 5; ++w) {
        IODeviceMemory *m = IODeviceMemory::withRange(kPhys[w], kLen[w]);
        if (!m) continue;
        gS->maps[w] = OSSharedPtr<IOMemoryMap>(m->map(kIOMapAnywhere | kIOMapInhibitCache), OSNoRetain);
        m->release();
        if (gS->maps[w]) {
            gS->va[w] = gS->maps[w]->getVirtualAddress();
            have |= (1u << w);
        }
    }
    IOLog("LQ102GPU MAP_BASE have=0x%x\n", have);
    usbFlush();

    gpb_io io{nullptr, gpbRd, gpbWr, delayUs};
    gpb_result r{};
    gpb_run(&io, 3u, have, &r);
    IOLog("LQ102GPU POWER gcc=%u cc=%u smmu=%u gpu=%u io=%d en_ahb=%u pw_cx=%u pw_clk=%u "
          "ahb=0x%x>0x%x cx=0x%x>0x%x gx=0x%x smmu_clk=0x%x "
          "smmu_id=0x%x/0x%x/0x%x scr0=0x%x gfsr=0x%x smr_valid=%u\n",
          unsigned(r.gcc), unsigned(r.cc), unsigned(r.smmu), unsigned(r.gpu), r.io_error,
          r.enabled_ahb, r.powered_cx, r.powered_clocks,
          r.cfg_ahb, r.cfg_ahb_after, r.cx_before, r.cx_gdscr, r.gx_gdscr, r.cc_smmu,
          r.id0, r.id1, r.id2, r.scr0, r.gfsr, r.smr_valid);
    usbFlush();
    if (r.smmu != GPB_DONE || r.io_error || !gpb_gdsc_on(r.cx_gdscr)) {
        IOLog("LQ102GPU STOP stage=power\n");
        usbFlush();
        return;
    }

    // Stage 4: GMU SMMU Context (bank 1, ASID 1, slot 2, SID 5)
    {
        IODeviceMemory *m = IODeviceMemory::withRange(GPB_SMMU_BASE, kSmmuWindow);
        if (m) {
            gS->smmuMap = OSSharedPtr<IOMemoryMap>(m->map(kIOMapAnywhere | kIOMapInhibitCache), OSNoRetain);
            m->release();
        }
    }
    if (!gS->smmuMap) { IOLog("LQ102GPU STOP stage=smmu_map\n"); usbFlush(); return; }

    IOReturn st = NativeAdrenoGmuContextBringup(
        reinterpret_cast<volatile uint8_t *>(gS->smmuMap->getVirtualAddress()),
        kSmmuWindow, kGmuBank, kGmuAsid, kGmuSlot, kGmuSid, nullptr, &gS->gmuCtx);
    IOLog("LQ102GPU GMUCTX st=0x%x step=%u prog=%u route=%u ttbr0=0x%llx sctlr=0x%x smr=0x%x s2cr=0x%x\n",
          unsigned(st), gS->gmuCtx.step, gS->gmuCtx.program_status, gS->gmuCtx.route_status,
          (unsigned long long)gS->gmuCtx.ttbr0, gS->gmuCtx.sctlr, gS->gmuCtx.smr, gS->gmuCtx.s2cr);
    usbFlush();
    if (st) { IOLog("LQ102GPU STOP stage=gmuctx\n"); usbFlush(); return; }

    // Stage 5-6: SM8475 GPUCC PLL0/PLL1, HUB 240 MHz, GMU 200 MHz, 7 GMU clocks
    gpb_result scratch = r;
    gpb_gmu_clocks clksBefore{}, clksAfter{};
    gpb_gmu_clock_on clkOn{};
    gpb_read_gmu_clocks(&io, &scratch, &clksBefore);
    gpb_gmu_clocks_on(&io, &scratch, &clksBefore, &clkOn);
    gpb_read_gmu_clocks(&io, &scratch, &clksAfter);
    IOLog("LQ102GPU GMUCLK step=%u fail=%d lock=%u hub_p=%u gmu_p=%u pll1=0x%x/0x%x hub=0x%x gmu=0x%x cx_gmu=0x%x vote=0x%x\n",
          clkOn.step, clkOn.failed, clkOn.lock_polls, clkOn.hub_polls, clkOn.gmu_polls,
          clksAfter.pll1_mode, clksAfter.pll1_opmode, clksAfter.hub_cfg & 0x7ffu, clksAfter.gmu_cfg & 0x7ffu,
          clksAfter.cx_gmu, (clksAfter.gpll0_vote >> 15) & 3u);
    usbFlush();
    if (clkOn.step != 7 || clkOn.failed) { IOLog("LQ102GPU STOP stage=gmuclk\n"); usbFlush(); return; }

    // Stage 6B: Live 128 KiB cmd-db read & HFI startup config build
    gS->cmdDb = static_cast<uint8_t *>(IOMallocData(kCmdDbBytes));
    if (!gS->cmdDb) { IOLog("LQ102GPU STOP stage=cmddb_oom\n"); usbFlush(); return; }
    {
        IODeviceMemory *m = IODeviceMemory::withRange(kCmdDbBase, kCmdDbBytes);
        OSSharedPtr<IOMemoryMap> dbMap;
        if (m) {
            dbMap = OSSharedPtr<IOMemoryMap>(m->map(kIOMapAnywhere | kIOMapInhibitCache | kIOMapReadOnly), OSNoRetain);
            m->release();
        }
        if (!dbMap) { IOLog("LQ102GPU STOP stage=cmddb_map\n"); usbFlush(); return; }
        const volatile uint32_t *src = reinterpret_cast<const volatile uint32_t *>(dbMap->getVirtualAddress());
        for (size_t i = 0; i < kCmdDbBytes / 4; ++i) {
            uint32_t w = src[i];
            memcpy(gS->cmdDb + 4 * i, &w, 4);
        }
    }
    uint32_t dbVer = 0, dbMagic = 0;
    memcpy(&dbVer, gS->cmdDb, 4);
    memcpy(&dbMagic, gS->cmdDb + 4, 4);
    gS->voteInputs = {};
    gS->voteInputs.chip_id = kChipIdA730;
    ShengGmuDbStatus dbSt = ShengGmuCommandDbInputs(gS->cmdDb, kCmdDbBytes, dbVer, &gS->voteInputs);
    AdrenoHfiStartupStatus hfiBuildSt = (dbSt == ShengGmuDbSuccess)
        ? ShengGmuBuildStartup(&gS->voteInputs, &gS->startup)
        : AdrenoHfiStartupInvalid;
    IOLog("LQ102GPU CMDDB ver=0x%x magic=0x%08x parse=%u build=%u gmxc=%u sh0=0x%x mc0=0x%x acv=0x%x cn0=0x%x\n",
          dbVer, dbMagic, unsigned(dbSt), unsigned(hfiBuildSt), gS->voteInputs.gmxc_present,
          gS->voteInputs.sh0.address, gS->voteInputs.mc0.address, gS->voteInputs.acv.address, gS->voteInputs.cn0_address);
    usbFlush();
    if (dbSt != ShengGmuDbSuccess || hfiBuildSt != AdrenoHfiStartupSuccess) {
        IOLog("LQ102GPU STOP stage=cmddb\n");
        usbFlush();
        return;
    }

    // Stage 7: Bind 5 GMU windows + 5 payload WC mappings & run ShengGmuColdStart
    for (unsigned w = 0; w < 5; ++w) {
        IODeviceMemory *m = IODeviceMemory::withRange(kColdPhys[w], kColdLen[w]);
        if (m) {
            gS->coldMaps[w] = OSSharedPtr<IOMemoryMap>(m->map(kIOMapAnywhere | kIOMapInhibitCache), OSNoRetain);
            m->release();
        }
        if (!gS->coldMaps[w]) { IOLog("LQ102GPU STOP stage=cold_map_%u\n", w); usbFlush(); return; }
        gS->coldMmio.windows[w] = {
            reinterpret_cast<volatile unsigned char *>(gS->coldMaps[w]->getVirtualAddress()),
            kColdPhys[w], size_t(kColdLen[w])
        };
    }
    NativeAdrenoGmuPayload payloads[5]{};
    st = NativeAdrenoGmuContextPayloads(payloads);
    if (st) { IOLog("LQ102GPU STOP stage=payloads st=0x%x\n", unsigned(st)); usbFlush(); return; }
    ShengGmuMemory *memPtrs[5] = {
        &gS->coldConfig.icache, &gS->coldConfig.dummy, &gS->coldConfig.debug,
        &gS->coldConfig.log, &gS->coldConfig.hfi
    };
    for (unsigned i = 0; i < 5; ++i) {
        IODeviceMemory *m = IODeviceMemory::withRange(payloads[i].physical, payloads[i].bytes);
        if (m) {
            gS->payloadMaps[i] = OSSharedPtr<IOMemoryMap>(m->map(kIOMapAnywhere | kIOMapWriteCombineCache), OSNoRetain);
            m->release();
        }
        if (!gS->payloadMaps[i]) { IOLog("LQ102GPU STOP stage=payload_map_%u\n", i); usbFlush(); return; }
        *memPtrs[i] = {
            reinterpret_cast<volatile uint32_t *>(gS->payloadMaps[i]->getVirtualAddress()),
            payloads[i].bytes, payloads[i].iova
        };
    }
    gS->coldDevice = {};
    if (ShengGmuBindMmio(&gS->coldMmio, &gS->coldDevice.io) != ShengGmuSuccess) {
        IOLog("LQ102GPU STOP stage=bind_mmio\n");
        usbFlush();
        return;
    }
    gS->coldDevice.services = {nullptr, coldSha256, coldNow, coldWait};
    gS->coldConfig.chip_id = kChipIdA730;
    gS->coldConfig.firmware = native_adreno_firmware_image;
    gS->coldConfig.firmware_bytes = size_t(native_adreno_firmware_image_size);
    gS->coldConfig.poll_budget = 200;

    // Clear AO IRQs and read pre-boot GMU state
    gS->coldDevice.io.write32(gS->coldDevice.io.cookie, ShengGmuCore, kAoIrqClr, ~0u);
    gS->coldDevice.io.write32(gS->coldDevice.io.cookie, ShengGmuCore, kAoIrqMask, ~kAoFatal);
    gS->coldDevice.io.barrier(gS->coldDevice.io.cookie);
    uint32_t preReset = *reinterpret_cast<volatile uint32_t *>(gS->coldMmio.windows[0].cpu + kGmuSysReset);
    uint32_t preRet   = *reinterpret_cast<volatile uint32_t *>(gS->coldMmio.windows[4].cpu + kCxMiscTcmRet);
    uint32_t preRsc   = *reinterpret_cast<volatile uint32_t *>(gS->coldMmio.windows[1].cpu + kRsccSeqBusy);
    uint32_t preHfi   = *reinterpret_cast<volatile uint32_t *>(gS->coldMmio.windows[0].cpu + kGmuHfiStatus);
    IOLog("LQ102GPU GMU_PRE reset=%x tcm_ret=%x rsc_busy=%x hfi_st=%x\n", preReset, preRet, preRsc, preHfi);
    usbFlush();

    const ShengGmuStartupLimits limits = {1000, 100, 50000, 2000000};
    ShengGmuStatus cs = ShengGmuColdStart(&gS->coldDevice, &gS->coldConfig, &gS->startup, &limits, &gS->coldResult);
    const ShengGmuResult &lr = gS->coldResult.load;
    const AdrenoHfiStartupResult &pr = gS->coldResult.protocol;
    IOLog("LQ102GPU COLDSTART st=%u phase=%u hash=%u fw_res=0x%x hfi_st=0x%x fw_rdy=%u hfi_rdy=%u "
          "ao_flt=0x%x cm3_flt=0x%x proto=%u pstage=%u ack=0x%x fw_err=0x%x cmds=%u ms=%llu\n",
          unsigned(cs), lr.phase, lr.complete_hash_verified, lr.firmware_init_result, lr.hfi_status,
          lr.firmware_ready_observed, lr.hfi_ready_observed, lr.ao_fault_status, lr.cm3_fault_status,
          unsigned(gS->coldResult.protocol_status), unsigned(pr.stage), pr.acknowledged_stages,
          pr.firmware_error, pr.published_commands, (unsigned long long)(pr.elapsed_us / 1000ULL));
    usbFlush();
    if (cs != ShengGmuSuccess) { IOLog("LQ102GPU STOP stage=coldstart\n"); usbFlush(); return; }

    // Stage 8: GX_BW_PERF_VOTE + OOB GPU_SET -> GX ON
    gS->coldDevice.io.write32(gS->coldDevice.io.cookie, ShengGmuCore, kG2hClr, ~0u);
    gS->coldDevice.io.write32(gS->coldDevice.io.cookie, ShengGmuCore, kG2hMask, ~(1u << 23));
    gS->coldDevice.io.barrier(gS->coldDevice.io.cookie);
    uint32_t gxBefore = gmuRd(0x1f8d0);
    unsigned perf = 1u, bw = 1u;
    perf = ShengGmuPerfVote(perf, &bw);
    gS->perfVote[0] = perf; gS->perfVote[1] = bw;
    const uint32_t vote[3] = {1u, perf, bw};
    uint32_t hfiOut[16] = {}, hfiErr = 0;
    size_t hfiCount = 0;
    AdrenoHfiStatus vst = AdrenoHfiExchange(&gS->coldDevice.hfi, 30, vote, 3, 1000, hfiWait, hfiOut, 16, &hfiCount, &hfiErr);
    unsigned ackPolls = 101;
    if (vst == AdrenoHfiSuccess) {
        gS->coldDevice.io.write32(gS->coldDevice.io.cookie, ShengGmuCore, kH2gSet, 1u << 30);
        gS->coldDevice.io.barrier(gS->coldDevice.io.cookie);
        for (ackPolls = 1; ackPolls <= 100; ++ackPolls) {
            uint32_t info = 0;
            gS->coldDevice.io.read32(gS->coldDevice.io.cookie, ShengGmuCore, kG2hInfo, &info);
            if (info & (1u << 31)) break;
            IODelay(100);
        }
        gS->coldDevice.io.write32(gS->coldDevice.io.cookie, ShengGmuCore, kG2hClr, 1u << 31);
        gS->coldDevice.io.barrier(gS->coldDevice.io.cookie);
    }
    uint32_t gxAfter = gmuRd(0x1f8d0);
    uint32_t gxGdscr = *reinterpret_cast<volatile uint32_t *>(gS->va[GPB_WIN_GPUCC] + GPB_CC_GX_GDSCR);
    bool isGxOn = (ackPolls <= 100) && !(gxAfter & 3u);
    uint32_t rbbm = isGxOn ? gpuRd(A740_RBBM_STATUS) : 0xdeadbeefu;
    uint32_t gbif = isGxOn ? gpuRd(A740_GBIF_HALT) : 0xdeadbeefu;
    IOLog("LQ102GPU GX_ON vote=%u err=0x%x ack=%u gx=0x%x>0x%x gdscr=0x%x on=%u rbbm=0x%x gbif=0x%x\n",
          unsigned(vst), hfiErr, ackPolls, gxBefore, gxAfter, gxGdscr, isGxOn ? 1u : 0u, rbbm, gbif);
    usbFlush();
    if (!isGxOn) { IOLog("LQ102GPU STOP stage=gx_on\n"); usbFlush(); return; }

    // Stage 9: GPU SMMU bank 0 (SIDs 0/1) + SQE + A730 hw_init + Ring 0 + CP_ME_INIT + Scratch write
    st = NativeAdrenoGpuContextBringup(
        reinterpret_cast<volatile uint8_t *>(gS->smmuMap->getVirtualAddress()),
        kSmmuWindow, 0, 2, 0, 0, 1, 1, nullptr, &gS->gpuCtx);
    IOLog("LQ102GPU GPUCTX st=0x%x step=%u prog=%u route=%u spans=%u ias=%u\n",
          unsigned(st), gS->gpuCtx.step, gS->gpuCtx.program_status, gS->gpuCtx.route_status,
          gS->gpuCtx.spans, NativeAdrenoGpuContextInputBits());
    usbFlush();
    if (st) { IOLog("LQ102GPU STOP stage=gpuctx\n"); usbFlush(); return; }

    gpuSetActlr();
    if (NativeAdrenoGpuContextBuffers(gS->gpuBuffers)) {
        IOLog("LQ102GPU STOP stage=gpu_buffers\n");
        usbFlush();
        return;
    }
    for (unsigned i = 0; i < GpuBufferCount; ++i) {
        IODeviceMemory *m = IODeviceMemory::withRange(gS->gpuBuffers[i].physical, gS->gpuBuffers[i].bytes);
        if (m) {
            gS->gpuMaps[i] = OSSharedPtr<IOMemoryMap>(m->map(kIOMapAnywhere | kIOMapWriteCombineCache), OSNoRetain);
            m->release();
        }
        if (!gS->gpuMaps[i]) { IOLog("LQ102GPU STOP stage=gpu_buf_map_%u\n", i); usbFlush(); return; }
        gS->gpuCpu[i] = reinterpret_cast<volatile uint8_t *>(gS->gpuMaps[i]->getVirtualAddress());
    }

    // Upload a730_sqe.fw (skip first dword header, per adreno_fw_create_bo)
    const uint64_t sqeSize = native_adreno_sqe_firmware_image_size;
    if (sqeSize < 8 || sqeSize - 4 > gS->gpuBuffers[0].bytes) {
        IOLog("LQ102GPU STOP stage=sqe_size sz=%llu buf=%llu\n",
              (unsigned long long)sqeSize, (unsigned long long)gS->gpuBuffers[0].bytes);
        usbFlush();
        return;
    }
    for (uint64_t i = 4; i < sqeSize; ++i) gS->gpuCpu[0][i - 4] = native_adreno_sqe_firmware_image[i];
    __asm__ volatile("dsb sy" ::: "memory");

    gpuHwInit();

    const NativeAdrenoRingIo rio{nullptr, ringWrite, ringRead, ringBarrier, nullptr, nullptr};
    const NativeAdrenoRingCache rcache{nullptr, ringPublish, ringAcquire};
    native_adreno_fence_phys = gS->gpuBuffers[2].physical;
    st = gS->ring.attach(&rio, &rcache, const_cast<uint8_t *>(gS->gpuCpu[1]), gS->gpuBuffers[1].bytes,
                         gS->gpuBuffers[1].iova, const_cast<uint8_t *>(gS->gpuCpu[2]),
                         gS->gpuBuffers[2].bytes, gS->gpuBuffers[2].iova);
    if (st) { IOLog("LQ102GPU STOP stage=ring_attach st=0x%x\n", unsigned(st)); usbFlush(); return; }
    gpuWr64(A740_CP_BV_RB_RPTR_ADDR, gS->gpuBuffers[2].iova + 8u);
    gpuWr(A740_CP_SQE_CNTL, 1u);

    size_t pwrupWritten = 0;
    uint32_t *pwrupStage = static_cast<uint32_t *>(IOMallocData(gS->gpuBuffers[3].bytes));
    if (!pwrupStage) { IOLog("LQ102GPU STOP stage=pwrup_oom\n"); usbFlush(); return; }
    st = NativeAdrenoPwrupList::buildA740(ringRead, nullptr, reinterpret_cast<uint8_t *>(pwrupStage),
                                          gS->gpuBuffers[3].bytes, &pwrupWritten);
    if (!st) {
        volatile uint32_t *dst32 = reinterpret_cast<volatile uint32_t *>(gS->gpuCpu[3]);
        const size_t nwords = gS->gpuBuffers[3].bytes / 4u;
        for (size_t i = 0; i < nwords; ++i) dst32[i] = pwrupStage[i];
    }
    IOFreeData(pwrupStage, gS->gpuBuffers[3].bytes);
    if (st) { IOLog("LQ102GPU STOP stage=pwrup st=0x%x\n", unsigned(st)); usbFlush(); return; }
    __asm__ volatile("dsb sy" ::: "memory");

    const NativeAdrenoCpInitConfig cpCfg{gS->gpuBuffers[0].iova, gS->gpuBuffers[3].iova, 1};
    uint32_t fence = 0, seen = 0;
    st = gS->cpInit.run(&rio, &gS->ring, &cpCfg, &fence);
    const NativeAdrenoRingClock clock{nullptr, ringNow, ringIdle};
    NativeAdrenoRingFence f1 = st ? NativeAdrenoRingFenceTimeout : gS->ring.wait(fence, &clock, 200000, &seen);
    IOLog("LQ102GPU CP_INIT st=0x%x f1=%u fence=%u seen=%u rbbm=0x%x int0=0x%x hwflt=0x%x rptr=%u wptr=%u fsr=0x%x\n",
          unsigned(st), unsigned(f1), fence, seen, gpuRd(A740_RBBM_STATUS), gpuRd(A740_RBBM_INT_0_STATUS),
          gpuRd(A740_CP_HW_FAULT), gpuRd(A740_CP_RB_RPTR), gpuRd(A740_CP_RB_WPTR), gpuFsr());
    usbFlush();
    if (st || f1 != NativeAdrenoRingFenceComplete) { IOLog("LQ102GPU STOP stage=cp_init\n"); usbFlush(); return; }

    // Scratch CP_MEM_WRITE test (0x5e9a730)
    volatile uint32_t *scratchBuf = reinterpret_cast<volatile uint32_t *>(gS->gpuCpu[4]);
    scratchBuf[0] = 0;
    __asm__ volatile("dsb sy" ::: "memory");
    uint32_t wWords[4] = {};
    if (AdrenoPM4Type7(0x3d, 3, &wWords[0]) != AdrenoPM4Success) { IOLog("LQ102GPU STOP stage=pm4\n"); return; }
    wWords[1] = uint32_t(gS->gpuBuffers[4].iova);
    wWords[2] = uint32_t(gS->gpuBuffers[4].iova >> 32);
    wWords[3] = 0x5e9a730u;
    st = gS->ring.submit(wWords, 4, &fence);
    NativeAdrenoRingFence f2 = st ? NativeAdrenoRingFenceTimeout : gS->ring.wait(fence, &clock, 200000, &seen);
    uint32_t gotScratch = scratchBuf[0];
    IOLog("LQ102GPU SCRATCH st=0x%x f2=%u fence=%u seen=%u word=0x%08x ok=%u fsr=0x%x\n",
          unsigned(st), unsigned(f2), fence, seen, gotScratch, (f2 == NativeAdrenoRingFenceComplete && gotScratch == 0x5e9a730u) ? 1u : 0u, gpuFsr());
    usbFlush();
    if (f2 != NativeAdrenoRingFenceComplete || gotScratch != 0x5e9a730u) {
        IOLog("LQ102GPU STOP stage=scratch\n");
        usbFlush();
        return;
    }

    // Stage 10: ZAP PAS authentication + CP_SET_SECURE_MODE 0
    bool zapOk = loadZapAndLeaveSecureMode();
    IOLog("LQ102GPU ZAP_RESULT ok=%u\n", zapOk ? 1u : 0u);
    usbFlush();

    // Stage 11: Bulk CP_MEMCPY + SPI 300 (INTID 332) IRQ attach
    {
        for (unsigned i = 1; i < 1024; ++i) scratchBuf[i] = 0;
        __asm__ volatile("dsb sy" ::: "memory");
        uint32_t cWords[8] = {};
        int copied = -1;
        if (AdrenoPM4Type7(0x75, 5, &cWords[0]) == AdrenoPM4Success &&
            AdrenoPM4Type7(0x12, 0, &cWords[6]) == AdrenoPM4Success) {
            const uint64_t srcIova = gS->gpuBuffers[0].iova, dstIova = gS->gpuBuffers[4].iova + 4u;
            cWords[1] = 1023;
            cWords[2] = uint32_t(srcIova); cWords[3] = uint32_t(srcIova >> 32);
            cWords[4] = uint32_t(dstIova); cWords[5] = uint32_t(dstIova >> 32);
            if (cpFence(cWords, 7)) {
                const volatile uint32_t *sqeW = reinterpret_cast<const volatile uint32_t *>(gS->gpuCpu[0]);
                copied = 0;
                for (unsigned i = 0; i < 1023; ++i) copied += (scratchBuf[1 + i] == sqeW[i]);
            }
        }
        uint32_t rb = 0;
        uint64_t router = ~0ULL;
        IOReturn irqSt = armcpu_spi_attach ? armcpu_spi_attach(332, false, gpuIrq, nullptr, &rb, &router) : kIOReturnUnsupported;
        gS->irqAttached = (irqSt == kIOReturnSuccess);
        IOSleep(20);
        uint32_t n1 = gS->irqCount;
        uint32_t nop = 0;
        bool nopOk = (AdrenoPM4Type7(0x10, 0, &nop) == AdrenoPM4Success) && cpFence(&nop, 1);
        IOSleep(20);
        uint32_t n2 = gS->irqCount;
        IOLog("LQ102GPU IRQ_MEMCPY copied=%d/1023 attach=0x%x rb=0x%x n=%u->%u nop=%u seen=0x%x\n",
              copied, unsigned(irqSt), rb, n1, n2, nopOk ? 1u : 0u, gS->irqSeen);
        usbFlush();
    }

    // Stage 12: Coherence, CP aperture, Publish NativeAdrenoGpu & AGXAccelerator
    NativeAdrenoVm *vm = NativeAdrenoGpuContextVm();
    if (vm) {
        gS->submit.attach(vm, &gS->ring);
        native_adreno_dram_read32 = dramRead32;
        native_adreno_cached_read32 = cachedRead32;
        native_adreno_line_audit = lineAudit;
        coherenceProbe(vm);
        native_adreno_wc_enabled = 0u;
        openCpAperture();
        IOReturn tSt = gS->timer.attach(&kTimerIo, NativeAdrenoTimeCp);
        const unsigned ias = NativeAdrenoGpuContextInputBits();
        gS->devInfo.va_size = ias > 32 ? ((1ULL << ias) - GpuClientVaStart) : 0ULL;
        native_adreno_set_restart(gpuRestart, nullptr);
        IOReturn pubSt = native_adreno_publish(vm, &gS->submit, &gS->ring, &clock,
                                               tSt ? nullptr : &gS->timer, &gS->devInfo, ias, 40);
        IOLog("LQ102GPU PUBLISH st=0x%x timer=0x%x ias=%u va_size=0x%llx table_mode=%u cpchk=%x,%x,%x,%x,%x,%x\n",
              unsigned(pubSt), unsigned(tSt), ias, (unsigned long long)gS->devInfo.va_size,
              native_adreno_cp_aperture[3],
              native_adreno_cp_check[0], native_adreno_cp_check[1], native_adreno_cp_check[2],
              native_adreno_cp_check[3], native_adreno_cp_check[4], native_adreno_cp_check[5]);
        usbFlush();

        if (!pubSt) {
            publishMetalAccelerator();
            usbFlush();
        }
    }

    IOLog("LQ102GPU DONE ok=1 zap=%u\n", gS->zapLoaded ? 1u : 0u);
    usbFlush(10000);

    // Periodic GPU + Display telemetry monitor (every 5s)
    for (unsigned tick = 1; tick <= 120; ++tick) {
        IOSleep(5000);
        uint32_t sub = 0, ret = 0;
        (void)native_adreno_fences(&sub, &ret);
        const auto &d = native_adreno_metal_diag;
        const uint32_t mt = d.marks_total;
        uint32_t m0 = mt >= 4 ? d.marks[(mt - 4) & 15] : 0;
        uint32_t m1 = mt >= 3 ? d.marks[(mt - 3) & 15] : 0;
        uint32_t m2 = mt >= 2 ? d.marks[(mt - 2) & 15] : 0;
        uint32_t m3 = mt >= 1 ? d.marks[(mt - 1) & 15] : 0;
        IOLog("LQ102GPU STAT t=%u gpu(open=%u call=%u sub=%u ret=%u hang=%u/%u views=%u/%u/%u marks=%u:%x,%x,%x,%x opener=%.16s)\n",
              tick * 5, d.opens, d.calls, sub, ret, native_adreno_recovery[0], native_adreno_recovery[1],
              native_adreno_view_diag[0], native_adreno_view_diag[1], native_adreno_view_diag[3],
              mt, m0, m1, m2, m3, d.opener[0]);
        IOLog("LQ102GPU DISP t=%u stg=%u cli=%u acc=%u rej=%u(r=%u w=%llu h=%llu fmt=0x%llx pl=%llu st=%llu al=%llu dl=%llu sz=%ux%u r0=%u,%u,%u,%u ms=%x,%x,%x op=%x,%x,%x) xfer=%u(0x%x) copy=%llu ret=%u frm=%u ss=%u,%u,%u,%u,%u\n",
              tick * 5, native_legacy_stage, native_legacy_client_calls,
              native_legacy_swap_accepted_count, native_legacy_swap_rejected_count, native_legacy_rej_reason,
              (unsigned long long)native_legacy_rej_surface[0], (unsigned long long)native_legacy_rej_surface[1],
              (unsigned long long)native_legacy_rej_surface[2], (unsigned long long)native_legacy_rej_surface[3],
              (unsigned long long)native_legacy_rej_surface[4],
              (unsigned long long)native_legacy_rej_surface[5], (unsigned long long)native_legacy_rej_surface[6],
              native_legacy_rej_size[0], native_legacy_rej_size[1],
              native_legacy_rej_rects[0][0], native_legacy_rej_rects[0][1],
              native_legacy_rej_rects[0][2], native_legacy_rej_rects[0][3],
              native_legacy_rej_state[0], native_legacy_rej_state[1], native_legacy_rej_state[2],
              native_legacy_rej_options[0], native_legacy_rej_options[1], native_legacy_rej_options[2],
              native_legacy_transfer_calls, (unsigned)native_legacy_transfer_status,
              (unsigned long long)native_legacy_copy_n, native_legacy_retirement_calls, native_legacy_frame_count,
              native_legacy_swapstat[0], native_legacy_swapstat[1], native_legacy_swapstat[3],
              native_legacy_swapstat[7], native_legacy_swapstat[11]);
        {
            char prepBuf[224];
            prepBuf[0] = 0;
            native_legacy_prepare_report(prepBuf, sizeof(prepBuf));
            IOLog("LQ102GPU DCALL t=%u hp=%u vh=0x%llx c=%u,%u,%u,%u,%u,%u,%u,%u,%u,%u,%u,%u,%u,%u,%u,%u %s\n",
                  tick * 5, native_legacy_hotplug_state(), (unsigned long long)native_legacy_vsync_head(),
                  native_legacy_call_diag[0], native_legacy_call_diag[1], native_legacy_call_diag[2], native_legacy_call_diag[3],
                  native_legacy_call_diag[4], native_legacy_call_diag[5], native_legacy_call_diag[6], native_legacy_call_diag[7],
                  native_legacy_call_diag[8], native_legacy_call_diag[9], native_legacy_call_diag[10], native_legacy_call_diag[11],
                  native_legacy_call_diag[12], native_legacy_call_diag[13], native_legacy_call_diag[14], native_legacy_call_diag[15],
                  prepBuf);
            if (tick == 1 || tick == 3 || tick == 6 || tick == 9) {
                char stBuf[256];
                stBuf[0] = 0;
                native_legacy_fb_diag(stBuf, sizeof(stBuf));
                IOLog("LQ102GPU DSTATE t=%u pm(stg=%u st=0x%x c=%u cb=%u ord=%u) %s\n",
                      tick * 5, native_legacy_pm_stage, (unsigned)native_legacy_pm_status,
                      native_legacy_pm_calls, native_legacy_pm_callbacks, native_legacy_pm_ordinal, stBuf);
            }
        }
        if (d.report[0] || d.report2[0])
            IOLog("LQ102GPU REP t=%u r1=[%.63s] r2=[%.63s]\n", tick * 5, d.report, d.report2);
        if ((tick & 1) == 0) {
            for (unsigned ci = 0; ci < 8; ++ci) {
                if (native_adreno_client_text[ci].name[0]) {
                    IOLog("LQ102GPU CTXT t=%u [%u] %.19s: %.63s\n", tick * 5, ci,
                          native_adreno_client_text[ci].name, native_adreno_client_text[ci].text);
                }
            }
            for (unsigned ci = 0; ci < 8; ++ci) {
                const auto &c = native_adreno_client_log[ci];
                if (c.name[0]) {
                    IOLog("LQ102GPU CLOG t=%u [%u] %.19s op=%u ref=%u cls=%u pk=%uM err=0x%x\n",
                          tick * 5, ci, c.name, c.opens, c.refused, c.closes, c.peak_mib, c.last_refusal);
                }
            }
        }
    }
}

} // namespace

extern "C" void liuqin_gmu_trace(const char *tag, uint32_t a, uint32_t b) {
    (void)tag; (void)a; (void)b;
}

/* Exposes /chosen/memory-map/GpuAddon (loaded by DarwinBoot from kernel.macho.gpuaddon)
 * to XNU's native_gpu_addon_install() in kern_exec.c. */
extern "C" int native_ram_block_gpu_addon(const uint8_t **data, uint64_t *bytes) {
    if (!data || !bytes) return 0;
    *data = nullptr; *bytes = 0;
    IORegistryEntry *map = IORegistryEntry::fromPath("/chosen/memory-map", gIODTPlane);
    if (!map) return 0;
    OSData *range = OSDynamicCast(OSData, map->getProperty("GpuAddon"));
    uint64_t physical = 0, size = 0;
    if (range && range->getLength() == 16) {
        memcpy(&physical, range->getBytesNoCopy(), 8);
        memcpy(&size, static_cast<const uint8_t *>(range->getBytesNoCopy()) + 8, 8);
    }
    map->release();
    if (!size || size > (UINT64_C(64) << 20) || (physical & 4095) ||
        physical < gPhysBase || size > gPhysSize || physical - gPhysBase > gPhysSize - size)
        return 0;
    *data = reinterpret_cast<const uint8_t *>(ml_static_ptovirt(vm_offset_t(physical)));
    if (!*data) return 0;
    *bytes = size;
    return 1;
}

extern "C" void liuqin_gpu_bringup_start(void) {
    thread_t thread = nullptr;
    kern_return_t rc = kernel_thread_start(gpuBringupWorker, nullptr, &thread);
    if (rc == KERN_SUCCESS) thread_deallocate(thread);
    else IOLog("LQ102GPU SPAWN_ERR rc=0x%x\n", unsigned(rc));
}
