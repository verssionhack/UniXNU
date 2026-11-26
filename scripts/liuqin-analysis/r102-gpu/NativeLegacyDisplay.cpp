#define NATIVE_GPU_TRACE_OPTIONAL
#include "NativeGpuTrace.h"
#include "NativeLegacyRequest.h"
// SPDX-License-Identifier: BSD-2-Clause-Patent
// Reuse the unchanged original generic framebuffer implementation. Unknown
// backend leaves stop; this class is not yet a published system display.
#include "OriginalLegacyFramebufferABI.h"
#include "NativeGOPWire.h"
#include "NativeHalfCodes.h"
#include <IOKit/IOLib.h>
#include <IOKit/IOMemoryDescriptor.h>
#include <IOKit/IOWorkLoop.h>
#include <IOKit/IOUserClient.h>
#include <IOKit/IOTimerEventSource.h>
#include <IOKit/IODeviceMemory.h>
#include <kern/clock.h>
#include <IOKit/pwr_mgt/IOPM.h>
#include <IOKit/pwr_mgt/IOPMpowerState.h>
#include <libkern/c++/OSData.h>
#include <libkern/c++/OSDictionary.h>
#include <libkern/c++/OSNumber.h>
#include <pexpert/pexpert.h>
#if defined(NATIVE_LEGACY_MACOS) && NATIVE_LEGACY_MACOS
#include <IOKit/IODeviceTreeSupport.h>
#include <libkern/OSKextLib.h>
#include <kern/thread.h>
#endif
extern "C" __attribute__((noreturn)) void native_legacy_backend_guard(unsigned,void *,void *);
extern "C" IOService *native_legacy_display_allocate(void);
extern "C" bool native_legacy_gop_mapping_observed(IOService *,IOMemoryMap *,uint32_t,uint32_t);
extern "C" void native_legacy_registration_observed(IOService *);
extern "C" void native_legacy_swap_stage(unsigned);
extern "C" void native_legacy_client_enter(task_t,uint32_t);
extern "C" void native_legacy_client_observed(IOReturn,IOUserClient *);
extern "C" void native_legacy_pm_observed(unsigned,IOReturn,unsigned long);
extern "C" IOMemoryDescriptor *native_legacy_surface_descriptor(OSObject *);
extern "C" uint64_t native_legacy_surface_width(OSObject *),native_legacy_surface_height(OSObject *);
extern "C" uint64_t native_legacy_surface_stride(OSObject *),native_legacy_surface_allocation(OSObject *);
extern "C" uint32_t native_legacy_surface_format(OSObject *),native_legacy_surface_planes(OSObject *);
extern "C" void native_legacy_frame_observed(unsigned kind,uint64_t count,uint64_t minx,uint64_t miny,uint64_t maxx,uint64_t maxy);
extern "C" void native_legacy_frame_colors_observed(const uint32_t *colors,const uint64_t *counts,uint64_t other);
extern "C" void native_legacy_swap_validation_observed(bool,unsigned,const void *,const void *);
// The surface of a rejected swap, as the validator read it: width, height, format, planes, stride, allocation, descriptor length.
extern "C" void native_legacy_surface_rejected(uint64_t,uint64_t,uint32_t,uint32_t,uint64_t,uint64_t,uint64_t);
extern "C" bool native_legacy_prepare_scanout(void);
extern "C" void native_legacy_transfer_observed(IOReturn,const void *,uint64_t);
extern "C" void native_legacy_copy_timing_observed(uint64_t ticks,uint64_t bytes);
extern "C" void native_legacy_retirement_observed(IOService *);
// GPU hand-off (boot-arg fb-gpu=1): the frame is offered to the privileged GPU client instead of being copied; the swap retires when the
// client reports the GPU copy done (native_legacy_gpu_complete). A refused offer or a failed copy uses the CPU copy below and is counted.
// format: NGP_BGRX8888, or for a half-float surface NGP_RGBA16F_LINEAR / NGP_RGBA16F_ENCODED (the client converts it on the GPU).
extern "C" bool native_legacy_gpu_offer(void *display,IOMemoryDescriptor *,uint64_t stride,uint32_t width,uint32_t height,uint32_t format);
// The compositor's swapped surfaces, for a display that fetches them itself: [0] distinct surfaces seen, [1] swaps checked; for the first four, at
// [2 + 3 * k]: allocation bytes, physical segments, largest segment (KiB). The pages are wired for the count and released.
extern "C" {volatile uint32_t native_legacy_surfaces[14];}
// Direct scanout (dpu-scanout=2): the display's two pipes fetch the compositor's surface through the display bank's window
// (NativeUfs native_ufs_dpu_map). [0] flips, [1] surfaces mapped, [2] map failures, [3] latches that took over 50 ms, [4] longest latch (us),
// [5] latch total (us, for the mean), [6] surfaces let go, [7] swaps that fell back to the copy, [8] flips back to the boot memory,
// [9] swaps held back until the GPU had written the frame (the compositor submits the swap when the command buffer is scheduled), [10] total
// and [11] longest wait (us), [12] waits that reached 250 ms, [13] waits of 8 ms or more (longer than a refresh at 120 Hz: the frame missed a flip).
extern "C" {volatile uint32_t native_legacy_direct[14];}
extern "C" bool native_adreno_fences(uint32_t *submitted,uint32_t *retired) __attribute__((weak_import));
extern "C" bool native_adreno_fences_detail(uint32_t *,uint32_t *,uint32_t *) __attribute__((weak_import));
// The swap lifecycle: native_legacy_ring holds the newest native_legacy_ring_cap events (allocated at start: a static array of this size no longer fits the kernel's data segment), {[0] microseconds since boot (64 bit), [1] event << 56 | slot + 1 << 48 |
// swaps validated and not retired << 40 | GPU fences outstanding << 24 | the request's tag (24 bits)}. Events: 1 swap validated, 2 fence wait
// begun, 3 fence passed, 4 flipped to a slot, 5 latched, 6 retired, 7 offered to the GPU copy, 8 blank frame. native_legacy_snap is the 64
// events before the first swap whose validation to flip took over 100 ms (native_legacy_snap_count 1 once taken). native_legacy_swapstat:
// [0] swaps validated, [1] kicks, [2] kicks refused for a swap in flight (transferred), [3] refused while the display is not ready, [4] with no
// validated head, [5] direct flips refused for a latch in flight, [6] fence waits begun, [7] swaps that took the copy path, [8] blank frames,
// [9] flips, [10] latches, [11] retires, [12] validation to flip over 100 ms, [13] the longest (us), [14] their total (us), [15] most swaps
// validated and not yet retired.
extern "C" {volatile uint64_t native_legacy_center_half[2];}
extern "C" {volatile uint64_t (*native_legacy_ring)[2]=nullptr;volatile uint32_t native_legacy_ring_cap=0;volatile uint32_t native_legacy_ring_count;volatile uint64_t native_legacy_snap[64][2];volatile uint32_t native_legacy_snap_count;volatile uint32_t native_legacy_swapstat[16];}
extern "C" uint32_t native_ufs_dpu_map(unsigned slot,const uint64_t *pages,unsigned count) __attribute__((weak_import));
extern "C" volatile uint32_t native_ufs_dpu_state __attribute__((weak_import));
static void noteSurface(OSObject *surface,IOMemoryDescriptor *memory)
{
    static OSObject *seen[4];
    native_legacy_surfaces[1]=native_legacy_surfaces[1]+1;
    for(OSObject *known:seen)if(known==surface)return;
    const unsigned k=native_legacy_surfaces[0];
    native_legacy_surfaces[0]=k+1;
    if(k>=4)return;
    seen[k]=surface;
    if(memory->prepare()!=kIOReturnSuccess)return;
    uint32_t segments=0;uint64_t largest=0;
    for(IOByteCount offset=0,length=0;offset<memory->getLength() && segments<100000;offset+=length,++segments) {
        if(!memory->getPhysicalSegment(offset,&length,kIOMemoryMapperNone) || !length)break;
        if(length>largest)largest=length;
    }
    memory->complete();
    native_legacy_surfaces[2+3*k]=uint32_t(memory->getLength());native_legacy_surfaces[3+3*k]=segments;native_legacy_surfaces[4+3*k]=uint32_t(largest>>10);
}
extern "C" void native_legacy_gpu_fallback_observed(int status);
// Swaps retired when the GPU client took the frame (before its copy finished), and copies that then failed after such a retirement.
extern "C" {volatile uint64_t native_legacy_early_retires,native_legacy_early_failures;}
// Swaps the family gave up on after waiting 5 s for them (cancelSwapsAfterTimeout).
extern "C" {volatile uint64_t native_legacy_swap_timeouts;}
// Display refresh tick (boot-arg vsync=<Hz>, 0 or absent: off). The original family sends the compositor's vsync message (type 5)
// through native_legacy_vsync_notify, the unchanged original sender, but only a platform subclass calls it from the panel's vblank and
// that subclass is not part of this port: without it the render server never saw a vsync. The GOP scanout has no vblank interrupt, so a
// work-loop timer stands in for it while at least one client has vsync notifications enabled. Events: 0 armed, 1 sent, 2 idle (no client),
// 3 late (deadline passed, cadence restarted), 4 started, 5 refresh properties reported at that rate.
extern "C" void native_legacy_vsync_notify(void *display,uint64_t timestamp,uint64_t continuousTime,uint64_t interval);
// The panel's refresh rate in Hz for the tick and the refresh properties below (0: none, the render server's own 1/60 s). By default
// boot-arg vsync; a platform may answer otherwise (its display device's mode).
extern "C" __attribute__((weak)) unsigned native_legacy_refresh_hz(void) {
    unsigned hz=0;PE_parse_boot_argn("vsync",&hz,sizeof(hz));return hz;
}
// The unchanged original setDisplayRefreshProperties: publishes IOMFBDisplayRefresh from slot 301 (getRefreshAttributes below).
extern "C" bool native_legacy_set_refresh_properties(void *display);
extern "C" void native_legacy_vsync_observed(unsigned event,unsigned hz);
extern "C" uint64_t mach_continuous_time(void);
extern "C" void flush_dcache64(addr64_t addr,unsigned count,int phys);
extern "C" vm_offset_t ml_static_ptovirt(vm_offset_t paddr);
extern "C" unsigned int pmap_cache_attributes(unsigned int pn);
// 32-bit BGRA, plain ('BGRA') or in Apple's lossless-compressed spelling ('&BGA', one plane): the GPU that renders the surface here writes plain rows
// either way (no compression is implemented), so the bytes are the same.
static inline bool nativeBgra(uint32_t format,uint32_t planes) {
    return (format==0x42475241 && !planes) || (format==0x26424741 && planes<=1);
}
// 64-bit RGBA half float ('RGhA', one plane): iPadOS 27's render server picks it for this panel's framebuffer once a Metal device renders
// (every Metal frame was refused while only BGRA was taken). The copy converts it to the scanout's BGRA (convertHalfRows below).
static inline bool nativeHalf(uint32_t format,uint32_t planes) {return format==0x52476841 && !planes;}
static inline bool nativeScanoutFormat(uint32_t format,uint32_t planes) {return nativeBgra(format,planes) || nativeHalf(format,planes);}
// One byte per positive half bit pattern (32768); negative values and NaNs give 0, values of 1.0 and above 255.
static uint8_t *halfTable() {
    static uint8_t *table;
    if(table)return table;
    uint8_t *made=static_cast<uint8_t *>(IOMalloc(32768));
    if(!made)return nullptr;
    unsigned mode=1;PE_parse_boot_argn("fb-half",&mode,sizeof(mode));
    const uint16_t *thresholds=mode==2?native_half::kEncoded:native_half::kLinear;
    unsigned code=0;
    for(unsigned bits=0;bits<32768;++bits) {
        while(code<255 && bits>=thresholds[code])++code;
        made[bits]=(bits>=0x7c00)?(bits==0x7c00?255:0):uint8_t(code);
    }
    if(!__sync_bool_compare_and_swap(&table,(uint8_t *)nullptr,made))IOFree(made,32768);
    return table;
}
// Rows of RGBA half floats to the scanout's BGRA rows (alpha opaque). Returns false when the table cannot be made or a row runs past either end.
static bool convertHalfRows(volatile void *dst,uint64_t dstLength,uint64_t dstStride,const void *src,uint64_t srcLength,uint64_t srcStride,
                            uint32_t width,uint32_t height) {
    const uint8_t *table=halfTable();
    if(!table || dstStride<uint64_t(width)*4 || srcStride<uint64_t(width)*8 || !height ||
       dstStride*(height-1)+uint64_t(width)*4>dstLength || srcStride*(height-1)+uint64_t(width)*8>srcLength)return false;
    for(uint32_t y=0;y<height;++y) {
        const uint64_t *in=reinterpret_cast<const uint64_t *>(static_cast<const uint8_t *>(src)+srcStride*y);
        volatile uint32_t *out=reinterpret_cast<volatile uint32_t *>(static_cast<volatile uint8_t *>(dst)+dstStride*y);
        for(uint32_t x=0;x<width;++x) {
            const uint64_t p=in[x];
            const uint32_t r=uint32_t(p)&0xffff,g=uint32_t(p>>16)&0xffff,b=uint32_t(p>>32)&0xffff;
            const uint32_t rv=(r&0x8000)?0:table[r],gv=(g&0x8000)?0:table[g],bv=(b&0x8000)?0:table[b];
            out[x]=0xff000000u|(rv<<16)|(gv<<8)|bv;
        }
    }
    return true;
}
#if defined(NATIVE_LEGACY_MACOS) && NATIVE_LEGACY_MACOS
// macOS: the family's swap-info sender (swap_info_notify_dispatch_gated, bound by the build) and this kernel's own async result
// sender (protected in IOUserClient.h).
extern "C" void native_legacy_swap_info_dispatch(void *display,void *blob);
IOReturn nativeSendAsyncResult(io_user_reference_t *reference,IOReturn result,io_user_reference_t *args,UInt32 count,IOOptionBits options)
    __asm("__ZN12IOUserClient28sendAsyncResult64WithOptionsEPyiS0_jj");
// macOS reads the display's modes from its timing and color elements (CoreDisplay, WindowServer): IOAVFamily's constructors, bound
// by the build (IOAVVideoTimingElement::withData, ::setColorElements, IOAVVideoColorElement::withCapabilities). The enumerations
// are passed as their integer values.
extern "C" OSObject *native_legacy_ioav_timing(const void *data,uint32_t standardType,uint32_t timingStandard);
extern "C" void native_legacy_ioav_timing_colors(OSObject *timing,OSArray *colors);
// IOMobileFramebufferLegacy::hotPlug_notify(unsigned long long) (macOS): the digital out state IOMobileFramebufferGetDigitalOutState answers.
extern "C" void native_legacy_hotplug_notify(void *display,uint64_t state);
// The request fields validateSwap reads (rectangles, layer masks, options, dimensions, surfaces), for the rejection report of the board probe.
extern "C" const unsigned native_legacy_request_layout[6]={kRequestRect0,kRequestRect1,kRequestMasks,kRequestOptions,kRequestDims,kRequestSurfaces};
extern "C" OSObject *native_legacy_ioav_color(uint32_t standardType,uint32_t depth,uint32_t encoding,uint32_t range,uint32_t eotf,
    uint32_t colorimetry,bool,const OSDictionary *,const OSDictionary *,const OSDictionary *,const OSSet *);
// IOAVElement: its ID (u64) and score (u32); the byte after the score marks an invalid score (IOAVElement::init clears the ID,
// copyProperties reads all three, hasValidScore tests the byte, 26C5035r).
static constexpr unsigned kIOAVElementID=16,kIOAVElementScore=24;
static constexpr uint64_t kDisplayColorID=100;
static constexpr uint64_t kDisplayTiming120=1000,kDisplayTiming144=1001,kDisplayTiming60=1002;
#endif
class NativeLegacyDisplay;
static NativeLegacyDisplay *gDirectDisplay=nullptr;
static NativeLegacyDisplay *gLiveDisplay=nullptr;
extern "C" {
volatile uint32_t native_legacy_call_diag[16];
volatile uint32_t native_legacy_dpu_db[4]; /* [0] flips, [1] latch timeouts, [2] last latch us, [3] (enabled<<16)|pipes */
void liuqin_fb_suspend(int) __attribute__((weak_import));
uint32_t native_legacy_hotplug_state(void) {
    if(!gLiveDisplay)return 0xffffffffu;
    uint32_t v=0;memcpy(&v,reinterpret_cast<const unsigned char *>(gLiveDisplay)+0x2380,4);return v;
}
uint64_t native_legacy_vsync_head(void) {
    if(!gLiveDisplay)return 0;
    uint64_t v=0;memcpy(&v,reinterpret_cast<const unsigned char *>(gLiveDisplay)+kLegacyVsyncClients,8);return v;
}
}
static inline uint32_t bumpCall(unsigned idx) {
    uint32_t n=native_legacy_call_diag[idx]+1;native_legacy_call_diag[idx]=n;return n;
}
extern "C" void native_legacy_direct_snapshot(void);
extern "C" unsigned native_legacy_fb_diag(char *out,unsigned cap);
class NativeLegacyDisplay : public IOMobileFramebufferLegacy {
    OSDeclareDefaultStructors(NativeLegacyDisplay)
    IOMemoryMap *bootMapping=nullptr;
    void *shadow=nullptr;uint64_t shadowBytes=0;bool shadowValid=false;
    bool primary=false;
    bool logicalPM=false;
    bool transferred=false;
    // Every request the validator accepted and the family has not retired yet. A client may submit swap N+1 while swap N is still on the GPU
    // (int-131: swap 3 was validated during swap 2's GPU copy and one remembered pointer lost swap 2, which then never retired and left
    // every wait on it busy), so more than one can be pending.
    const OriginalLegacySwapRequest *validated[8]={};
    bool isValidated(const OriginalLegacySwapRequest *request) const {
        if(!request)return false;
        for(auto entry: validated)if(entry==request)return true;
        return false;
    }
    void removeValidated(const OriginalLegacySwapRequest *request) {for(unsigned i=0;i<8;++i)if(validated[i]==request){validated[i]=nullptr;validatedAt[i]=0;traceRequestIds[i]=0;}}
    uint64_t traceRequestIds[8];
    uint64_t traceNextRequest=0;
    uint64_t traceId(const OriginalLegacySwapRequest *r) {for(unsigned i=0;i<8;++i)if(validated[i]==r){if(!traceRequestIds[i])traceRequestIds[i]=++traceNextRequest;return traceRequestIds[i];}return 0;}
    uint64_t validatedAt[8];   // no initializer: IOKit objects are allocated zeroed, and a member memset would push the constructor's call to the original C2 out of the binding check's window
    static uint64_t nowUs() {uint64_t ns=0;absolutetime_to_nanoseconds(mach_absolute_time(),&ns);return ns/1000;}
    unsigned validatedCount() const {unsigned n=0;for(auto entry: validated)if(entry)++n;return n;}
    void stat(unsigned index) {native_legacy_swapstat[index]=native_legacy_swapstat[index]+1;}
    void note(unsigned event,int slot,const OriginalLegacySwapRequest *request) {
        if(&native_gpu_trace_enabled && native_gpu_trace_enabled()) {
            OSObject *surface=nullptr;
            if(request)memcpy(&surface,reinterpret_cast<const unsigned char *>(request)+kRequestSurfaces,sizeof(surface));
            IOMemoryDescriptor *memory=surface?native_legacy_surface_descriptor(surface):nullptr;
            uint64_t physical=0;
            // Validation precedes prepare(). Only a retained direct slot owns wired pages.
            for(const auto &wired:directSlots)if(wired.surface==surface && wired.memory==memory){physical=wired.physical;break;}
            gpuTraceEvent(GpuTraceDisplay,0,traceId(request),event,uint64_t(uintptr_t(request)),uint64_t(uintptr_t(surface)),physical,
                          slot,shownSlot,pendingSlot,validatedCount());
            if(surface && (event==1 || event==4))gpuTraceEvent(GpuTraceDisplaySurface,0,traceId(request),physical,native_legacy_surface_width(surface),
                native_legacy_surface_height(surface),native_legacy_surface_stride(surface),native_legacy_surface_format(surface),
                native_legacy_surface_allocation(surface),memory?memory->getLength():0);
        }
        uint32_t submitted=0,retired=0;uint32_t outstanding=0;
        if(&native_adreno_fences && native_adreno_fences(&submitted,&retired)){const int32_t d=int32_t(submitted-retired);outstanding=d>0?(d>255?255:uint32_t(d)):0;}
        if(!native_legacy_ring_cap)return;
        const uint32_t n=native_legacy_ring_count;volatile uint64_t *at=native_legacy_ring[n&(native_legacy_ring_cap-1)];
        at[0]=nowUs();
        at[1]=uint64_t(event)<<56|uint64_t(slot+1)<<48|uint64_t(validatedCount()&255)<<40|uint64_t(outstanding)<<24|((uintptr_t(request)>>4)&0xffffff);
        native_legacy_ring_count=n+1;
    }
    // Microseconds since this request was validated, 0 when it is not tracked.
    uint64_t sinceValidated(const OriginalLegacySwapRequest *request) const {
        for(unsigned i=0;i<8;++i)if(validated[i]==request && validatedAt[i])return nowUs()-validatedAt[i];
        return 0;
    }
    void noteFlipDelay(const OriginalLegacySwapRequest *request) {
        const uint64_t us=sinceValidated(request);
        if(!us)return;
        native_legacy_swapstat[14]=native_legacy_swapstat[14]+uint32_t(us);
        if(us>native_legacy_swapstat[13])native_legacy_swapstat[13]=uint32_t(us>0xffffffffull?0xffffffffull:us);
        if(us>100000) {
            stat(12);
            if(!native_legacy_snap_count && native_legacy_ring_cap) {
                const uint32_t n=native_legacy_ring_count;
                for(unsigned i=0;i<64;++i) {
                    const uint32_t from=n>=64?n-64+i:i;
                    const uint32_t mask=native_legacy_ring_cap-1;native_legacy_snap[i][0]=from<n?native_legacy_ring[from&mask][0]:0;native_legacy_snap[i][1]=from<n?native_legacy_ring[from&mask][1]:0;
                }
                native_legacy_snap_count=1;
            }
        }
    }
    void addValidated(const OriginalLegacySwapRequest *request) {
        if(isValidated(request))return;
        for(unsigned i=0;i<8;++i)if(!validated[i]){validated[i]=request;validatedAt[i]=nowUs();return;}
        validated[0]=request;validatedAt[0]=nowUs();
    }
    const OriginalLegacySwapRequest *gpuRequest=nullptr;
    uint64_t gpuTraceRequest=0;
    uint64_t gpuLength=0;
    bool gpuBypass=false;
    // The swap of the frame the GPU client is copying already retired (boot-arg early-retire, default 1). Retiring the offered
    // swap releases the frame shown before it, whose copy has finished (transferred held this one back); the offered frame itself stays
    // in use until the next swap retires, so the compositor never writes a frame the GPU is still reading.
    bool gpuRetired=false;
    // How a half-float surface is encoded (boot-arg fb-half=2: values already sRGB-encoded), as the GPU client converts it.
    static uint32_t halfOfferFormat() {
        unsigned mode=1;PE_parse_boot_argn("fb-half",&mode,sizeof(mode));
        return mode==2?NGP_RGBA16F_ENCODED:NGP_RGBA16F_LINEAR;
    }
    // The refresh tick runs on the family's work loop, the loop of the command gate that registers and removes the vsync clients, so the
    // client queue (kLegacyVsyncClients) never changes while the sender walks it.
    IOTimerEventSource *vsyncTimer=nullptr;
    uint64_t vsyncInterval=0,vsyncNext=0;
    unsigned vsyncHz=0;
    bool vsyncArmed=false;
    // Direct scanout state, used on the work loop only. DPU 9.2 inside the MDP block (0xae01000): VIG 0 and 1 at 0x4000 and 0x6000 (source
    // address 0 at +0x14, stride 0 at +0x24; VIG 1 takes the right half through its own source x), CTL 0 at 0x15000 (flush at +0x18, VIG 0
    // and 1 are bits 0 and 1). i562: a flush of the two pipes latched within 5.4 ms with no start (the panel refreshes by itself).
    struct DirectSlot {OSObject *surface;IOMemoryDescriptor *memory;uint32_t iova;uint64_t used,physical;};
    static constexpr unsigned kDirectSlots=4;
    DirectSlot directSlots[kDirectSlots]={};
    IOMemoryMap *mdpMap=nullptr;
    volatile uint32_t *mdp=nullptr;
    uint64_t *directPages=nullptr;
    IOTimerEventSource *latchTimer=nullptr;
    const OriginalLegacySwapRequest *latchRequest=nullptr;
    uint64_t latchStart=0,directClock=0;
    int shownSlot=-1,pendingSlot=-1;
    uint32_t shownStride=0;
    // Keep the first successful fence snapshot for this request across pending and busy polls.
    const OriginalLegacySwapRequest *fenceFor=nullptr;
    uint32_t fenceTarget=0;
    uint64_t fenceSince=0;
    bool fenceCaptured=false,fenceSlow=false;
    IOTimerEventSource *fenceTimer=nullptr;
    bool directOn=false,directBoot=true;
    // SM8475 DPU 8.1 hardware VSync double-buffering inside the 43 MiB firmware splash region
    // (0xb8000000 and 0xb9400000, both inside 0xb8000000..0xbab00000). Members left uninitialized
    // intentionally (IOKit zero-allocates objects; see validatedAt).
    IOMemoryMap *dbMdpMap;
    volatile uint32_t *dbMdp;
    IOMemoryMap *dbBuf1Map;
    uintptr_t dbBuf1Va;
    IOTimerEventSource *dbLatchTimer;
    const OriginalLegacySwapRequest *dbLatchRequest;
    uint64_t dbLatchStart;
    uint32_t dbPipeOff[4];
    uint32_t dbPipeDelta[4];
    uint32_t dbPipeCount;
    uint32_t dbFlushMask;
    unsigned dbFront;
    unsigned dbPendingBuf;
    bool dpuDbOn;
    static constexpr uint32_t kVig[2]={0x4000,0x6000},kCtlFlush=0x15018,kBootIova=0xb8000000U,kBootStride=0x2fa0;
    void startFenceTimer() {
        if(fenceTimer)return;
        IOWorkLoop *loop=getWorkLoop();
        IOTimerEventSource *t=loop?IOTimerEventSource::timerEventSource(this,&NativeLegacyDisplay::fenceFired):nullptr;
        if(t && loop->addEventSource(t)==kIOReturnSuccess)fenceTimer=t;
        else OSSafeReleaseNULL(t);
    }
    void startDpuDoubleBuf() {
        if(directOn || !primary || !bootMapping)return;
        unsigned enableDb=1;PE_parse_boot_argn("dpu-db",&enableDb,sizeof(enableDb));
        if(!enableDb)return;
        PE_Video video={};
        if(PE_current_console(&video) || bootMapping->getPhysicalAddress()!=kBootIova ||
           bootMapping->getLength()>0x1400000ULL || !video.v_rowBytes)return;
        IODeviceMemory *m=IODeviceMemory::withRange(0xae01000ULL,0x30000ULL);
        IOMemoryMap *mm=m?m->map(kIOMapAnywhere|kIOMapInhibitCache):nullptr;
        if(m)m->release();
        if(!mm)return;
        volatile uint32_t *reg=reinterpret_cast<volatile uint32_t *>(mm->getVirtualAddress());
        // SM8450/SM8475 DPU 8.1 SSPP catalog (dpu_8_1_sm8450.h / dpu_hw_ctl.c):
        static const struct {uint32_t off,bit;} kPipes[8]={
            {0x4000u,1u<<0},{0x6000u,1u<<1},{0x8000u,1u<<2},{0xa000u,1u<<18},
            {0x24000u,1u<<11},{0x26000u,1u<<12},{0x28000u,1u<<24},{0x2a000u,1u<<25},
        };
        uint32_t found=0,mask=0,firstFmt=0;
        for(unsigned i=0;i<8;++i) {
            const uint32_t addr=reg[(kPipes[i].off+0x14u)/4];
            const uint32_t stride=reg[(kPipes[i].off+0x24u)/4]&0xffffu;
            if(addr>=kBootIova && addr<0xb9400000u && stride==uint32_t(video.v_rowBytes) && found<4) {
                dbPipeOff[found]=kPipes[i].off;
                dbPipeDelta[found]=addr-kBootIova;
                mask|=kPipes[i].bit;
                if(!found)firstFmt=reg[(kPipes[i].off+0x30u)/4];
                ++found;
            }
        }
        const uint32_t ctlTop=reg[0x15014u/4],ctlFl0=reg[kCtlFlush/4];
        if(!found) {
            IOLog("LQ102GPU NLD DPU_DB no_pipes ctl_top=0x%x ctl_fl=0x%x\n",ctlTop,ctlFl0);
            mm->release();return;
        }
        // Verify CTL0 latches our SSPP flush mask on a harmless same-address flush before touching Buffer 1.
        reg[kCtlFlush/4]=mask;
        __asm__ volatile("dsb sy" ::: "memory");
        unsigned waitedUs=0;
        for(;waitedUs<20000 && (reg[kCtlFlush/4]&mask);waitedUs+=100)IODelay(100);
        if(reg[kCtlFlush/4]&mask) {
            IOLog("LQ102GPU NLD DPU_DB probe_timeout pipes=%u mask=0x%x fl=0x%x\n",found,mask,reg[kCtlFlush/4]);
            mm->release();return;
        }
        // Measure one full hardware vblank period via a 2nd back-to-back CTL_FLUSH latch right after latch 1.
        uint64_t tFrame0=mach_absolute_time();
        reg[kCtlFlush/4]=mask;
        __asm__ volatile("dsb sy" ::: "memory");
        unsigned frameWaitUs=0;
        for(;frameWaitUs<25000 && (reg[kCtlFlush/4]&mask);frameWaitUs+=100)IODelay(100);
        uint64_t frameNs=0;absolutetime_to_nanoseconds(mach_absolute_time()-tFrame0,&frameNs);
        uint32_t frameUs=uint32_t(frameNs/1000ull);
        uint32_t hwHz=(frameUs>=4000 && frameUs<=25000)?((1000000u+frameUs/2u)/frameUs):0u;
        IODeviceMemory *b1=IODeviceMemory::withRange(0xb9400000ULL,bootMapping->getLength());
        IOMemoryMap *b1m=b1?b1->map(kIOMapAnywhere|kIOMapWriteCombineCache):nullptr;
        if(b1)b1->release();
        IOWorkLoop *loop=getWorkLoop();
        IOTimerEventSource *lt=loop?IOTimerEventSource::timerEventSource(this,&NativeLegacyDisplay::dbLatchFired):nullptr;
        if(!b1m || !lt || loop->addEventSource(lt)!=kIOReturnSuccess) {
            OSSafeReleaseNULL(b1m);OSSafeReleaseNULL(lt);mm->release();return;
        }
        dbMdpMap=mm;dbMdp=reg;dbBuf1Map=b1m;dbBuf1Va=static_cast<uintptr_t>(b1m->getVirtualAddress());
        dbLatchTimer=lt;dbPipeCount=found;dbFlushMask=mask;dbFront=0;dbPendingBuf=0;dpuDbOn=true;
        native_legacy_dpu_db[3]=(1u<<16)|found;
        IOLog("LQ102GPU NLD DPU_DB ready pipes=%u mask=0x%x fmt=0x%x ctl_top=0x%x probe_us=%u frame_us=%u hw_hz=%u\n",
              found,mask,firstFmt,ctlTop,waitedUs,frameUs,hwHz);
    }
    void dbFlip(unsigned bufIdx) {
        const uint32_t base=bufIdx?0xb9400000u:kBootIova;
        for(uint32_t i=0;i<dbPipeCount;++i)dbMdp[(dbPipeOff[i]+0x14u)/4]=base+dbPipeDelta[i];
        __asm__ volatile("dsb sy" ::: "memory");
        dbMdp[kCtlFlush/4]=dbFlushMask;
        __asm__ volatile("dsb sy" ::: "memory");
    }
    void dbResetToBuf0() {
        if(!dpuDbOn)return;
        if(dbLatchTimer)dbLatchTimer->cancelTimeout();
        dbLatchRequest=nullptr;
        if(dbFront!=0){dbFlip(0);dbFront=0;}
    }
    static void dbLatchFired(OSObject *owner,IOTimerEventSource *) {static_cast<NativeLegacyDisplay *>(owner)->dbLatchTick();}
    void dbLatchTick() {
        if(!dbLatchRequest)return;
        uint64_t ns=0;absolutetime_to_nanoseconds(mach_absolute_time()-dbLatchStart,&ns);
        const bool pending=(dbMdp[kCtlFlush/4]&dbFlushMask)!=0;
        if(pending && ns<25000000ull){dbLatchTimer->setTimeoutUS(500);return;}
        const OriginalLegacySwapRequest *request=dbLatchRequest;dbLatchRequest=nullptr;
        if(pending) {
            native_legacy_dpu_db[1]=native_legacy_dpu_db[1]+1;
            if(native_legacy_dpu_db[0]==0) {
                dbFlip(0);dbFront=0;dpuDbOn=false;native_legacy_dpu_db[3]=dbPipeCount;
                IOLog("LQ102GPU NLD DPU_DB disabled after first flip timeout\n");
            }
        } else {
            dbFront=dbPendingBuf;
            native_legacy_dpu_db[0]=native_legacy_dpu_db[0]+1;
            native_legacy_dpu_db[2]=uint32_t(ns/1000);
        }
        finishTransfer(request);
    }
    void startDirect() {
        unsigned mode=0;PE_parse_boot_argn("dpu-scanout",&mode,sizeof(mode));
        if(mode<2 || !&native_ufs_dpu_map || !&native_ufs_dpu_state || !(native_ufs_dpu_state>>31) || !primary)return;
        IODeviceMemory *memory=IODeviceMemory::withRange(0xae01000,0x8f000);
        mdpMap=memory?memory->map(kIOMapAnywhere|kIOMapInhibitCache):nullptr;
        if(memory)memory->release();
        directPages=static_cast<uint64_t *>(IOMallocData(8192*sizeof(uint64_t)));
        IOWorkLoop *loop=getWorkLoop();
        latchTimer=loop?IOTimerEventSource::timerEventSource(this,&NativeLegacyDisplay::latchFired):nullptr;
        startFenceTimer();
        if(!mdpMap || !directPages || !latchTimer || !fenceTimer || loop->addEventSource(latchTimer)!=kIOReturnSuccess) {
            OSSafeReleaseNULL(mdpMap);OSSafeReleaseNULL(latchTimer);
            if(directPages){IOFreeData(directPages,8192*sizeof(uint64_t));directPages=nullptr;}
            return;
        }
        mdp=reinterpret_cast<volatile uint32_t *>(mdpMap->getVirtualAddress());
        directOn=true;gDirectDisplay=this;
    }
    // The diagnostic screenshot reads the boot memory, which the display no longer scans: draw the surface on screen into it (rows of the
    // visible width) so the picture shows what the panel shows.
    friend void native_legacy_direct_snapshot(void);
    void snapshot() {
        if(!directOn || directBoot || shownSlot<0 || !bootMapping || !shownStride)return;
        IOMemoryDescriptor *source=directSlots[shownSlot].memory;
        PE_Video video={};uint32_t width=0,height=0;getDisplayDimensions(&width,&height);
        if(!source || PE_current_console(&video) || video.v_baseAddr!=bootMapping->getPhysicalAddress() || video.v_width!=width || video.v_height!=height)return;
        uint8_t *out=reinterpret_cast<uint8_t *>(bootMapping->getVirtualAddress());
        for(uint32_t y=0;y<height && uint64_t(y+1)*video.v_rowBytes<=bootMapping->getLength();++y)
            if(source->readBytes(uint64_t(y)*shownStride,out+uint64_t(y)*video.v_rowBytes,uint64_t(width)*4)!=uint64_t(width)*4)return;
    }
    void flip(uint32_t iova,uint32_t stride) {
        shownStride=stride;
        for(uint32_t vig:kVig){mdp[(vig+0x14)/4]=iova;mdp[(vig+0x24)/4]=stride&0xffff;}
        __asm__ volatile("dsb sy" ::: "memory");
        mdp[kCtlFlush/4]=0x3;
        __asm__ volatile("dsb sy" ::: "memory");
    }
    // The slot that holds this surface, mapping it into a free one (never the one on screen or the one waiting to latch) the first time.
    int directSlot(OSObject *surface,IOMemoryDescriptor *memory) {
        ++directClock;
        int pick=-1;
        for(unsigned k=0;k<kDirectSlots;++k)if(directSlots[k].surface==surface && directSlots[k].memory==memory){directSlots[k].used=directClock;return int(k);}
        for(unsigned k=0;k<kDirectSlots;++k) {
            if(int(k)==shownSlot || int(k)==pendingSlot)continue;
            if(pick<0 || !directSlots[k].surface || (directSlots[pick].surface && directSlots[k].used<directSlots[pick].used))pick=int(k);
        }
        if(pick<0)return -1;
        DirectSlot &slot=directSlots[pick];
        if(slot.surface) {
            slot.memory->complete();OSSafeReleaseNULL(slot.memory);OSSafeReleaseNULL(slot.surface);
            native_legacy_direct[6]=native_legacy_direct[6]+1;
        }
        if(memory->getLength()>8192ull*4096 || memory->prepare()!=kIOReturnSuccess){native_legacy_direct[2]=native_legacy_direct[2]+1;return -1;}
        unsigned count=0;bool ok=true;
        for(IOByteCount offset=0;offset<memory->getLength() && ok;) {
            IOByteCount length=0;
            const addr64_t pa=memory->getPhysicalSegment(offset,&length,kIOMemoryMapperNone);
            if(!pa || (pa&0xfff) || !length){ok=false;break;}
            for(IOByteCount at=0;at<length && offset+at<memory->getLength();at+=4096)directPages[count++]=pa+at;
            offset+=length;
        }
        const uint32_t iova=ok?native_ufs_dpu_map(unsigned(pick),directPages,count):0;
        if(!iova){memory->complete();native_legacy_direct[2]=native_legacy_direct[2]+1;return -1;}
        surface->retain();memory->retain();
        slot={surface,memory,iova,directClock,directPages[0]};
        native_legacy_direct[1]=native_legacy_direct[1]+1;
        return pick;
    }
    // A provider's failed query is not completion. Poll without blocking the display work loop;
    // a slow GPU leaves the previous frame on screen until completion or family cancellation.
    bool traceGpuComplete=false;
    bool gpuWrote(const OriginalLegacySwapRequest *request) {
        traceGpuComplete=false;
        if(fenceFor!=request) {
            fenceFor=request;fenceTarget=0;fenceSince=0;fenceCaptured=false;fenceSlow=false;
        }
        uint32_t submitted=0,retired=0,detail[3]={0,0,4};
        // Preserve the CPU-only backend when no GPU fence interface is linked or fence timer is absent.
        if(!fenceTimer || (!&native_adreno_fences_detail && !&native_adreno_fences)) {
            gpuTraceEvent(GpuTraceDisplayFence,0,traceId(request),0,0,0,0,0,0,0,4);return true;
        }
        const bool known=&native_adreno_fences_detail?native_adreno_fences_detail(&submitted,&retired,detail):
            (&native_adreno_fences && native_adreno_fences(&submitted,&retired));
        // Before the GPU service is published (detail[2]==0), no GPU rendering exists yet: do not stall early frames.
        if(!known && &native_adreno_fences_detail && detail[2]==0) {
            fenceFor=nullptr;return true;
        }
        if(known && !fenceCaptured) {
            fenceTarget=submitted;fenceCaptured=true;
        }
        if(known && int32_t(retired-fenceTarget)>=0) {
            traceGpuComplete=true;
            gpuTraceEvent(GpuTraceDisplayFence,0,traceId(request),1,fenceTarget,submitted,retired,0,detail[0],detail[1],detail[2]);
            if(fenceSince)note(3,-1,request);
            if(fenceSince) {
                uint64_t ns=0;absolutetime_to_nanoseconds(mach_absolute_time()-fenceSince,&ns);
                const uint32_t us=uint32_t(ns/1000);
                native_legacy_direct[10]=native_legacy_direct[10]+us;
                if(us>native_legacy_direct[11])native_legacy_direct[11]=us;
                if(us>=8000)native_legacy_direct[13]=native_legacy_direct[13]+1;
            }
            fenceFor=nullptr;return true;
        }
        if(!fenceSince) {fenceSince=mach_absolute_time();native_legacy_direct[9]=native_legacy_direct[9]+1;stat(6);note(2,-1,request);}
        uint64_t ns=0;absolutetime_to_nanoseconds(mach_absolute_time()-fenceSince,&ns);
        if(ns>=250000000ull && !fenceSlow) {
            gpuTraceEvent(GpuTraceDisplayFence,0,traceId(request),2,fenceTarget,submitted,retired,ns,detail[0],detail[1],detail[2]);
            native_legacy_direct[12]=native_legacy_direct[12]+1;
            fenceSlow=true;
        }
        // If the GPU ring is poisoned (detail[2]==3) and 250 ms elapsed, fall through so the display does not freeze permanently.
        if(!known && detail[2]==3 && ns>=250000000ull) {
            fenceFor=nullptr;return true;
        }
        gpuTraceEvent(GpuTraceDisplayFence,0,traceId(request),known?3:4,fenceTarget,submitted,retired,ns,detail[0],detail[1],detail[2]);
        fenceTimer->setTimeoutUS(200);
        return false;
    }
    static void fenceFired(OSObject *owner,IOTimerEventSource *) {static_cast<NativeLegacyDisplay *>(owner)->fenceTick();}
    void fenceTick() {transferred=false;kickSwapQueue();}
    static void latchFired(OSObject *owner,IOTimerEventSource *) {static_cast<NativeLegacyDisplay *>(owner)->latchTick();}
    void latchTick() {
        if(!latchRequest)return;
        uint64_t ns=0;absolutetime_to_nanoseconds(mach_absolute_time()-latchStart,&ns);
        gpuTraceEvent(GpuTraceDisplayLatch,0,traceId(latchRequest),mdp[kCtlFlush/4],ns,shownSlot,pendingSlot);
        if((mdp[kCtlFlush/4]&0x3) && ns<50000000ull){latchTimer->setTimeoutUS(500);return;}
        if(ns>=50000000ull)native_legacy_direct[3]=native_legacy_direct[3]+1;
        const uint32_t us=uint32_t(ns/1000);
        if(us>native_legacy_direct[4])native_legacy_direct[4]=us;
        native_legacy_direct[5]=native_legacy_direct[5]+us;
        shownSlot=pendingSlot;pendingSlot=-1;
        stat(10);note(5,shownSlot,latchRequest);
        const OriginalLegacySwapRequest *request=latchRequest;latchRequest=nullptr;
        finishTransfer(request,true);
    }
    // Back to the boot loader's memory (the blank frame and the copy are drawn there).
    void directToBoot() {
        if(!directOn || directBoot)return;
        flip(kBootIova,kBootStride);directBoot=true;shownSlot=-1;
        native_legacy_direct[8]=native_legacy_direct[8]+1;
    }
    bool vsyncWanted() const {
        const void *head=nullptr;memcpy(&head,reinterpret_cast<const unsigned char *>(this)+kLegacyVsyncClients,sizeof(head));return head;
    }
    // Selector 72's registration of a vsync client ends in kickSwapQueue (slot 290), which arms the tick; the tick stops by itself once
    // the last client is removed.
    void armVsync() {
        if(!vsyncTimer || vsyncArmed || !vsyncWanted())return;
        vsyncArmed=true;vsyncNext=mach_absolute_time()+vsyncInterval;
        vsyncTimer->wakeAtTime(vsyncNext);native_legacy_vsync_observed(0,vsyncHz);
    }
    static void vsyncFired(OSObject *owner,IOTimerEventSource *) {static_cast<NativeLegacyDisplay *>(owner)->vsyncTick();}
    void vsyncTick() {
        vsyncArmed=false;
        if(!vsyncTimer)return;
        if(!vsyncWanted()){native_legacy_vsync_observed(2,vsyncHz);return;}
        const uint64_t now=mach_absolute_time();
        native_legacy_vsync_notify(this,now,mach_continuous_time(),vsyncInterval);
        native_legacy_vsync_observed(1,vsyncHz);
        vsyncNext+=vsyncInterval;
        if(vsyncNext<=now){vsyncNext=now+vsyncInterval;native_legacy_vsync_observed(3,vsyncHz);}
        vsyncArmed=true;vsyncTimer->wakeAtTime(vsyncNext);
    }
    void startVsync() {
        unsigned hz=effectiveRefreshHz();
        if(!hz || hz>240 || !primary || !bootMapping || vsyncTimer)return;
        IOWorkLoop *loop=getWorkLoop();
        if(!loop)return;
        IOTimerEventSource *timer=IOTimerEventSource::timerEventSource(this,&NativeLegacyDisplay::vsyncFired);
        if(!timer)return;
        if(loop->addEventSource(timer)!=kIOReturnSuccess){timer->release();return;}
        nanoseconds_to_absolutetime(1000000000ull/hz,&vsyncInterval);
        vsyncHz=hz;vsyncTimer=timer;native_legacy_vsync_observed(4,hz);
        // A client may already have registered: arm under the gate, like the registration does.
        loop->runAction([](OSObject *owner,void *,void *,void *,void *)->IOReturn {
            static_cast<NativeLegacyDisplay *>(owner)->armVsync();return kIOReturnSuccess;
        },this);
    }
    void stopVsync() {
        if(!vsyncTimer)return;
        vsyncTimer->cancelTimeout();
        if(IOWorkLoop *loop=getWorkLoop())loop->removeEventSource(vsyncTimer);
        OSSafeReleaseNULL(vsyncTimer);vsyncArmed=false;
    }
public:
    // Called by the GPU client's completion (any thread): the swap is finished on the framebuffer's work loop.
    void gpuComplete(int status) {
        struct Args {NativeLegacyDisplay *display;int status;} args={this,status};
        IOWorkLoop *loop=getWorkLoop();
        auto action=[](OSObject *,void *a0,void *,void *,void *)->IOReturn {
            Args *a=static_cast<Args *>(a0);a->display->finishGpuSwap(a->status);return kIOReturnSuccess;
        };
        if(loop)loop->runAction(action,this,&args);else finishGpuSwap(status);
    }
    unsigned fbDiag(char *out,unsigned cap) {
        const unsigned char *b=reinterpret_cast<const unsigned char *>(this);
        uint32_t swapId=0,req=0,pow=0,apiReq=0,apiPend=0,hp=0;
        uint64_t cur=0,pend=0,stq=0,pnot=0;
        memcpy(&swapId,b+0x21b8,4);memcpy(&req,b+0x21cc,4);memcpy(&pow,b+0x21d0,4);
        memcpy(&apiReq,b+0x21dc,4);memcpy(&apiPend,b+0x21e0,4);memcpy(&hp,b+0x2380,4);
        memcpy(&cur,b+0x2000,8);memcpy(&pend,b+0x2008,8);memcpy(&stq,b+0x2018,8);memcpy(&pnot,b+0x2038,8);
        return (unsigned)snprintf(out,cap,
            "lpm=%u pri=%u ps=%u b8c=0x%x sid=%u req=%u pow=%u api=%u/%u q=%u/%u/%u pn=%u hp=%u props=%u%u%u%u%u%u%u",
            (unsigned)logicalPM,(unsigned)primary,(unsigned)getPowerState(),(unsigned)b[0x8c],
            swapId,req,pow,apiReq,apiPend,cur?1u:0u,pend?1u:0u,stq?1u:0u,pnot?1u:0u,hp,
            getProperty("DisplayAttributes")?1u:0u,getProperty("ColorElements")?1u:0u,
            getProperty("TimingElements")?1u:0u,getProperty("IOMFBUUID")?1u:0u,
            getProperty("IOMFBNumLayers")?1u:0u,getProperty("DisplayWidth")?1u:0u,
            getProperty("DPTimingModeId")?1u:0u);
    }
    friend unsigned native_legacy_fb_diag(char *out,unsigned cap);
    void free() override {stopVsync();if(logicalPM){PMstop();logicalPM=false;}primary=false;OSSafeReleaseNULL(bootMapping);IOMobileFramebufferLegacy::free();}
    void stop(IOService *provider) override {
        stopVsync();
        transferred=false;for(auto &entry: validated)entry=nullptr;gpuRequest=nullptr;gpuRetired=false;
        directToBoot();latchRequest=nullptr;pendingSlot=-1;
        dbResetToBuf0();
        if(dbLatchTimer){dbLatchTimer->cancelTimeout();if(IOWorkLoop *loop=getWorkLoop())loop->removeEventSource(dbLatchTimer);OSSafeReleaseNULL(dbLatchTimer);}
        dpuDbOn=false;dbMdp=nullptr;dbBuf1Va=0;OSSafeReleaseNULL(dbBuf1Map);OSSafeReleaseNULL(dbMdpMap);
        if(fenceTimer){fenceTimer->cancelTimeout();if(IOWorkLoop *loop=getWorkLoop())loop->removeEventSource(fenceTimer);OSSafeReleaseNULL(fenceTimer);}
        if(latchTimer){latchTimer->cancelTimeout();if(IOWorkLoop *loop=getWorkLoop())loop->removeEventSource(latchTimer);OSSafeReleaseNULL(latchTimer);}
        directOn=false;
        if(logicalPM){PMstop();logicalPM=false;}
        primary=false;IOMobileFramebufferLegacy::stop(provider);OSSafeReleaseNULL(bootMapping);
    }
    // The panel is already lit by the firmware's GOP framebuffer, which is the one thing the original code's power-state word (the "powered" word
    // of the state pair) is meant to say; the platform subclass that normally writes it is not part of this
    // port, so without it the user client's wait (selector 6) answers kIOReturnBusy forever and the compositor never presents. This is the
    // original state setter (the virtual the original code calls with this same request shape) with only the powered word named.
    void announcePoweredByFirmware() {
        // Set both requested ([+0x21cc]) and powered ([+0x21d0]) to 1: on 26C5035r,
        // IOMobileFramebufferLegacy::swap_submit drops every swap silently (returning 0
        // without calling swap_queue/validateSwap) while requested==0.
        OriginalLegacyStateRequest request={0,1,0,1,1,{}};
        applyStateRequest(&request,false);
    }
    bool start(IOService *provider) override {
        if(!startDisplay(provider))return false;
        publishOneLayer();
        startVsync();startFenceTimer();startDirect();startDpuDoubleBuf();return true;
    }
    // CoreAnimation reads how many layers the display scans out from IOMFBNumLayers (MaxNumLayers). Without the property it may hand a
    // full-screen layer (an app's Metal layer) to the display as a detached layer of its own, copied through the IOSurfaceAccelerator
    // scaler, which does not exist here (backboardd aborts: "Failed to create IOSurfaceAccelerator"). This display scans out one layer.
    void publishOneLayer() {
        OSDictionary *layers=OSDictionary::withCapacity(1);
        OSNumber *count=OSNumber::withNumber(1ULL,32);
        if(layers && count && layers->setObject("MaxNumLayers",count))setProperty("IOMFBNumLayers",layers);
        OSSafeReleaseNULL(count);OSSafeReleaseNULL(layers);
    }
    bool startDisplay(IOService *provider) {
        if(!IOMobileFramebufferLegacy::start(provider))return false;
        if(!native_legacy_ring) {
            const uint32_t cap=65536;
            volatile uint64_t (*memory)[2]=(volatile uint64_t (*)[2])IOMallocZero(sizeof(uint64_t)*2*cap);
            if(memory) {native_legacy_ring=memory;native_legacy_ring_cap=cap;}
        }
        if(primary && bootMapping)announcePoweredByFirmware();
        unsigned enabled=0;PE_parse_boot_argn("offline-legacy-pm",&enabled,sizeof(enabled));
        if(!enabled)return true;
        unsigned phase=0;PE_parse_boot_argn("offline-legacy-phase",&phase,sizeof(phase));
        if(enabled!=1 || phase!=4 || !provider || !bootMapping || !primary) {
            native_legacy_pm_observed(1,kIOReturnNotReady,0);IOMobileFramebufferLegacy::stop(provider);return false;
        }
        // Actual IOKit PM lifecycle for logical scanout scheduling only. GOP
        // provides no panel power switch: neither state advertises physical
        // power output, power control or a hardware power transition.
        static IOPMPowerState states[2]={};
        states[0].version=states[1].version=1;
        states[1].capabilityFlags=kIOPMDeviceUsable;
        PMinit();logicalPM=initialized;
        if(!logicalPM){native_legacy_pm_observed(1,kIOReturnNotReady,0);IOMobileFramebufferLegacy::stop(provider);return false;}
        provider->joinPMtree(this);
        IOReturn regStatus=registerPowerDriver(this,states,2);native_legacy_pm_observed(1,regStatus,0);
        IOReturn status=regStatus;
        if(status==kIOReturnSuccess){status=changePowerStateToPriv(1);native_legacy_pm_observed(2,status,1);}
        {
            const unsigned char *b=reinterpret_cast<const unsigned char *>(this);
            uint32_t req=0,pow=0;uint8_t b8c=b[0x8c];
            memcpy(&req,b+0x21cc,4);memcpy(&pow,b+0x21d0,4);
            IOLog("LQ102GPU NLD startDisplay pm_en=%u ph=%u lpm=%u reg=0x%x chg=0x%x req=%u pow=%u b8c=0x%x ps=%u\n",
                  enabled,phase,(unsigned)logicalPM,(unsigned)regStatus,(unsigned)status,req,pow,(unsigned)b8c,(unsigned)getPowerState());
        }
        if(status!=kIOReturnSuccess){PMstop();logicalPM=false;IOMobileFramebufferLegacy::stop(provider);return false;}
        return true;
    }
    IOReturn setPowerState(unsigned long ordinal,IOService *device) override {
        const uint32_t n=bumpCall(10);
        if(!logicalPM)return IOMobileFramebufferLegacy::setPowerState(ordinal,device);
        if(ordinal>1 || !bootMapping){native_legacy_pm_observed(3,kIOReturnUnsupported,ordinal);return kIOReturnUnsupported;}
        native_legacy_pm_observed(3,kIOReturnSuccess,ordinal);
        IOReturn status=IOMobileFramebufferLegacy::setPowerState(ordinal,device);
        if(n<=8)IOLog("LQ102GPU NLD setPowerState(%lu) -> 0x%x\n",ordinal,(unsigned)status);
        native_legacy_pm_observed(4,status,ordinal);return status;
    }
    // The explicit offline system-client experiment publishes only the real
    // GOP mode. Unknown backend calls retain their stop-with-caller guards.
    void registerService(IOOptionBits options=0) override {
        unsigned enabled=0;PE_parse_boot_argn("offline-legacy-register",&enabled,sizeof(enabled));
        if(enabled!=1)native_legacy_backend_guard(84,this,__builtin_return_address(0));
        // Nothing in the family publishes IOMFBDisplayRefresh (its platform subclass does), and without it the render server keeps its own
        // 1/60 s heartbeat (int-210: refresh=0). Publish it before any client can find the display, only when vsync asks for more.
        unsigned hz=effectiveRefreshHz();
        if(primary && hz>60 && hz<=240)native_legacy_set_refresh_properties(this);
        IOService::registerService(options);native_legacy_registration_observed(this);
    }
    bool isMainDisplay() override {return primary;}
    // The render server paces its display timer by the minimum refresh interval in IOMFBDisplayRefresh (int-209: no vsync client ever
    // registered, frames came every 16.7 ms), and the generic slot 301 fixes it at 1/60 s. With vsync=<Hz> it reports the panel's
    // own rate instead; the maximum interval and the step keep the original values. Words in 32.32 seconds, then their mach times.
    // The original maximum interval is 1/24 s (int-240), which offers the render server a 24 to vsync Hz range. The panel has no
    // variable refresh, so vsync-fixed=1 reports the maximum interval equal to the minimum: one fixed rate.
    unsigned activeRefreshHz=0;
    unsigned effectiveRefreshHz() const {
        if(activeRefreshHz>=60 && activeRefreshHz<=240)return activeRefreshHz;
        unsigned hz=native_legacy_refresh_hz();
        return (hz>=60 && hz<=240)?hz:120u;
    }
    bool getRefreshAttributes(uint64_t *words,bool fixed) override {
        const uint32_t n=bumpCall(9);
        if(!IOMobileFramebufferLegacy::getRefreshAttributes(words,fixed) || !words)return false;
        unsigned hz=effectiveRefreshHz();
        if(n<=4)IOLog("LQ102GPU NLD getRefreshAttributes(fixed=%u) hz=%u w0=0x%llx w2=0x%llx\n",(unsigned)fixed,hz,(unsigned long long)words[0],(unsigned long long)words[2]);
        if(hz<=60 || hz>240)return true;
        unsigned locked=0;PE_parse_boot_argn("vsync-fixed",&locked,sizeof(locked));
        const uint64_t interval=(1ull<<32)/hz;
        uint64_t machTime=0;nanoseconds_to_absolutetime(interval*1000000000ull>>32,&machTime);
        words[0]=interval;words[1]=machTime;
        if(fixed || locked==1){words[2]=interval;words[3]=machTime;}
        native_legacy_vsync_observed(5,hz);
        return true;
    }
    // A swap the client submitted while the previous one was still on its way (transferred) is not kicked by the family again: without the
    // re-kick after each retirement it waited for the next submission (int-143: every offer came one frame late, a still screen showed the
    // previous frame until the user touched it again). A retirement inside a kick only asks the running kick to loop.
    bool kicking=false,rekick=false;
    void kickSwapQueue() override {
        const uint32_t n=bumpCall(12);
        if(n<=8)IOLog("LQ102GPU NLD kickSwapQueue #%u vsyncWanted=%u\n",n,(unsigned)vsyncWanted());
        armVsync();
        if(kicking){rekick=true;return;}
        kicking=true;
        do {
            rekick=false;
            kickOnce();
            gpuBypass=false;
        } while(rekick && !transferred);
        kicking=false;
    }
    void kickOnce() {
        unsigned enabled=0;PE_parse_boot_argn("offline-legacy-transfer",&enabled,sizeof(enabled));
        stat(1);
        if(enabled!=1 || !logicalPM || !bootMapping || !primary){stat(3);return;}
        if(transferred){stat(2);return;}
        const OriginalLegacySwapRequest *request=pendingSwapRequest();
        if(!request || !isValidated(request)){stat(4);return;}
        // This bounded first-frame transfer preserves the original queue's
        // resource ownership. Separately gated retirement follows the copy;
        // neither path signals a hardware fence, announces a vblank or
        // claims general producer synchronization.
        // The owned GPU instrument completes its work before submission.
        // The separate original software-renderer experiment uses completed
        // synchronous CPU surfaces, with no GPU or display fence fabricated.
        OSObject *surface=nullptr;
        memcpy(&surface,reinterpret_cast<const unsigned char *>(request)+kRequestSurfaces,sizeof(surface));
        if(!surface) {
            // Validated blank swap (all layers disabled over black): solid-fill the actual GOP.
            PE_Video blank={};
            uint32_t bw=0,bh=0;getDisplayDimensions(&bw,&bh);
            uint64_t blankLength=(uint64_t)bw*bh*4;
            const bool dimOk=!PE_current_console(&blank) && blank.v_baseAddr==bootMapping->getPhysicalAddress() &&
                blank.v_depth==32 && !blank.v_rotate &&
                ((blank.v_width==bw && blank.v_height==bh) || (blank.v_width==bh && blank.v_height==bw)) &&
                native_legacy_surface_bounds((uint32_t)blank.v_width,(uint32_t)blank.v_height,blank.v_rowBytes,bootMapping->getLength(),bootMapping->getLength());
            if(!dimOk) {
                native_legacy_transfer_observed(kIOReturnNotReady,request,0);return;
            }
            if(!native_legacy_prepare_scanout()) {native_legacy_transfer_observed(kIOReturnNotReady,request,0);return;}
            directToBoot();
            dbResetToBuf0();
            if(!native_legacy_fill_pixels(reinterpret_cast<volatile void *>(bootMapping->getVirtualAddress()),
                bootMapping->getLength(),blank.v_rowBytes,(uint32_t)blank.v_width,(uint32_t)blank.v_height,0xff000000U)) {
                native_legacy_transfer_observed(kIOReturnBadArgument,request,0);return;
            }
            __asm__ volatile("dsb sy" ::: "memory");
            shadowValid=false;
            transferred=true;
            native_legacy_frame_observed(1,0,0,0,0,0);
            stat(8);note(8,-1,request);
            {const uint32_t colors[4]={0xff000000U,0,0,0};const uint64_t counts[4]={(uint64_t)bw*bh,0,0,0};native_legacy_frame_colors_observed(colors,counts,0);}
            native_legacy_transfer_observed(kIOReturnSuccess,request,blankLength);
            finishTransfer(request);
            return;
        }
        if(!surface->metaCast("IOSurface"))return;
        IOMemoryDescriptor *memory=native_legacy_surface_descriptor(surface);
        PE_Video video={};
        uint32_t width=0,height=0;getDisplayDimensions(&width,&height);
        uint64_t length=(uint64_t)width*height*4;
        uint64_t sourceStride=native_legacy_surface_stride(surface);
        uint64_t allocation=native_legacy_surface_allocation(surface);
        const bool videoOk=!PE_current_console(&video) && video.v_baseAddr==bootMapping->getPhysicalAddress() &&
            video.v_depth==32 && !video.v_rotate &&
            ((video.v_width==width && video.v_height==height) || (video.v_width==height && video.v_height==width)) &&
            native_legacy_surface_bounds((uint32_t)video.v_width,(uint32_t)video.v_height,video.v_rowBytes,bootMapping->getLength(),bootMapping->getLength());
        if(!memory || !memory->metaCast("IOMemoryDescriptor") || !native_legacy_surface_bounds(width,height,sourceStride,allocation,memory->getLength()) ||
           native_legacy_surface_width(surface)<width || native_legacy_surface_height(surface)<height ||
           !nativeScanoutFormat(native_legacy_surface_format(surface),native_legacy_surface_planes(surface)) ||
           !videoOk) {
            native_legacy_transfer_observed(kIOReturnNotReady,request,0);return;
        }
        const bool rotated=(video.v_width==height && video.v_height==width);
        // The diagnostic renderer repaints the page over the scanout until it is told the system owns the display; the GPU path needs that as much
        // as the CPU copy (int-093: accepted swaps were GPU-copied under a page that kept drawing).
        if(!gpuBypass) {
            if(!native_legacy_prepare_scanout()) {native_legacy_transfer_observed(kIOReturnNotReady,request,0);return;}
        }
        noteSurface(surface,memory);
        const bool half=nativeHalf(native_legacy_surface_format(surface),native_legacy_surface_planes(surface));
        if(half) {
            // Every 32nd half-float frame: the centre pixel's four raw components and the sample count, for the boot log. They tell
            // whether a compositor writes linear or encoded values (a mid grey is 0.214 linear and 0.5 encoded).
            static uint32_t tick;
            if((tick++&31)==0) {
                uint16_t pixel[4]={};
                IOMemoryDescriptor *descriptor=OSDynamicCast(IOMemoryDescriptor,memory);
                const uint64_t offset=(uint64_t)(height/2)*sourceStride+(uint64_t)(width/2)*8;
                if(descriptor && offset+8<=descriptor->getLength() && descriptor->readBytes(offset,pixel,8)==8) {
                    native_legacy_center_half[0]=(uint64_t)pixel[0]|(uint64_t)pixel[1]<<16|(uint64_t)pixel[2]<<32|(uint64_t)pixel[3]<<48;
                    native_legacy_center_half[1]=native_legacy_center_half[1]+1;
                }
            }
        }
        if(directOn && !half && !gpuBypass && latchRequest)stat(5);
        if(directOn && !half && !gpuBypass && !latchRequest) {
            if(!gpuWrote(request)) {transferred=true;return;}
            const int slot=directSlot(surface,memory);
            if(slot>=0) {
                native_legacy_swap_stage(1);
                flip(directSlots[slot].iova,uint32_t(sourceStride));directBoot=false;
                native_legacy_direct[0]=native_legacy_direct[0]+1;
                stat(9);note(4,slot,request);noteFlipDelay(request);
                shadowValid=false;pendingSlot=slot;latchRequest=request;transferred=true;
                latchStart=mach_absolute_time();latchTimer->setTimeoutUS(500);
                return;
            }
            native_legacy_direct[7]=native_legacy_direct[7]+1;
        }
        directToBoot();
        stat(7);note(7,-1,request);
        if(!gpuBypass && native_legacy_gpu_offer(this,memory,sourceStride,width,height,half?halfOfferFormat():NGP_BGRX8888)) {
            // The GPU writes the scanout memory behind the CPU's back: the differential copy's picture of it is stale from now on.
            native_legacy_swap_stage(1);
            shadowValid=false;gpuRequest=request;gpuTraceRequest=traceId(request);gpuLength=length;transferred=true;
            // The compositor renders the next frame only after this swap retires, so retiring at the end of the copy serialized render and
            // copy (int-243: about 4.4 ms render then about 3 ms copy per frame). Retire now: the presenter holds its own reference to this
            // frame's memory, the previous frame's copy has finished (transferred held this one back), and the next swap still waits for
            // the copy because transferred stays set until finishGpuSwap.
            unsigned early=1;PE_parse_boot_argn("early-retire",&early,sizeof(early));
            if(early==1 && retireSwap(request,true)) {
                gpuRetired=true;native_legacy_early_retires=native_legacy_early_retires+1;
            }
            return;
        }
        // Wait for every GPU command buffer scheduled before this swap to retire before the CPU
        // invalidates cache and reads the IOSurface: WindowServer submits swaps at schedule time,
        // so copying earlier captures half-rendered sysmem frames (flashing/disappearing UI parts).
        if(!gpuWrote(request)) {transferred=true;return;}
        // Zero-trap direct physical-segment BGRA copy via permanent 1:1 kernel linear map (ml_static_ptovirt):
        // avoids creating/tearing down a 20 MiB lazy kernel_map view and taking 5,130 L3 page faults per frame on 4 KiB XNU.
        if(!half) {
            if(!native_legacy_prepare_scanout()) {
                native_legacy_transfer_observed(kIOReturnNotReady,request,0);return;
            }
            if(memory->prepare()!=kIOReturnSuccess) {
                native_legacy_transfer_observed(kIOReturnNoMemory,request,0);return;
            }
            uint64_t copyStart;__asm__ volatile("isb\n\tmrs %0, cntpct_el0":"=r"(copyStart));
            const bool useDb=(dpuDbOn && rotated);
            const unsigned nextBuf=useDb?(1u-dbFront):0u;
            const uintptr_t dstBase=useDb?(nextBuf?dbBuf1Va:static_cast<uintptr_t>(bootMapping->getVirtualAddress()))
                :static_cast<uintptr_t>(bootMapping->getVirtualAddress());
            const uint64_t dstStride=video.v_rowBytes;
            const uint64_t rowBytes=uint64_t(width)*4;
            const uint64_t totalNeed=sourceStride*(height-1)+rowBytes;
            const uint64_t memLen=memory->getLength();
            static uint32_t sFrameNo=0;
            const uint32_t fno=++sFrameNo;
            const bool doSample=(fno<=5 || fno==10 || fno==20 || fno==40 || (fno%50)==0);
            uint32_t sLit=0,sTotal=0,sCols[4]={};uint32_t sColCnt[4]={};unsigned sUsed=0;
            bool ok=false;
            if(rotated && (width&7)==0 && (height&7)==0 && (dstBase&7)==0 && (dstStride&7)==0) {
                const uint32_t physW=(uint32_t)video.v_width;
                const uint32_t physH=(uint32_t)video.v_height;
                const uint64_t needPages=(totalNeed+4095ULL)>>12;
                static const uint8_t **sPageVa=nullptr;
                static uint64_t sPageCap=0;
                if(needPages>sPageCap) {
                    const uint8_t **fresh=static_cast<const uint8_t **>(IOMalloc(size_t(needPages)*sizeof(const uint8_t *)));
                    if(fresh) {
                        if(sPageVa)IOFree(sPageVa,size_t(sPageCap)*sizeof(const uint8_t *));
                        sPageVa=fresh;sPageCap=needPages;
                    }
                }
                ok=(sPageVa && needPages<=sPageCap && totalNeed<=memLen &&
                    dstStride>=uint64_t(physW)*4 && dstStride*(physH-1)+uint64_t(physW)*4<=bootMapping->getLength());
                uint64_t off=0;
                while(ok && off<totalNeed) {
                    IOByteCount segLen=0;
                    const addr64_t phys=memory->getPhysicalSegment(off,&segLen,kIOMemoryMapperNone);
                    if(!phys || !segLen || (off&4095ULL)){ok=false;break;}
                    const uint64_t useLen=(off+segLen>totalNeed)?(totalNeed-off):uint64_t(segLen);
                    const vm_offset_t srcVa=ml_static_ptovirt(vm_offset_t(phys));
                    if(!srcVa){ok=false;break;}
                    flush_dcache64((addr64_t)srcVa,(unsigned)useLen,false);
                    const uint64_t basePage=off>>12;
                    const uint64_t segPages=(useLen+4095ULL)>>12;
                    const uint8_t *basePtr=reinterpret_cast<const uint8_t *>(srcVa);
                    for(uint64_t p=0;p<segPages && basePage+p<needPages;++p)
                        sPageVa[basePage+p]=basePtr+(p<<12);
                    off+=useLen;
                }
                if(ok) {
                    uint64_t rotStart=0;__asm__ volatile("isb\n\tmrs %0, cntpct_el0":"=r"(rotStart));
                    constexpr uint64_t kOpaqueAlpha=0xff000000ff000000ULL;
                    constexpr uint64_t kLo32=0x00000000ffffffffULL;
                    constexpr uint64_t kHi32=0xffffffff00000000ULL;
                    if((sourceStride&31ULL)==0) {
                        // Fast register-tiled 90-degree CCW transpose:
                        // ly0 outer in 16-row strips (64-byte full WC cache-line bursts per dst row) + 8-row tail;
                        // lx0 inner in 8-pixel (32-byte) sequential chunks (never crosses a 4 KiB page boundary).
                        uint32_t ly0=0;
                        for(;ly0+16<=height;ly0+=16) {
                            uint64_t rb[16];
                            for(uint32_t r=0;r<16;++r)rb[r]=uint64_t(ly0+r)*sourceStride;
                            const uint64_t dstColOff=uint64_t(physW-16-ly0)*4;
                            for(uint32_t lx0=0;lx0<width;lx0+=8) {
                                const uint64_t lxBytes=uint64_t(lx0)*4;
                                const uint64_t *p[16];
                                for(uint32_t r=0;r<16;++r) {
                                    const uint64_t bo=rb[r]+lxBytes;
                                    p[r]=reinterpret_cast<const uint64_t *>(sPageVa[bo>>12]+(bo&4095ULL));
                                }
                                if(doSample && (ly0&63)==32 && (lx0&63)==0) {
                                    const uint32_t px=uint32_t(p[0][0]);
                                    ++sTotal;
                                    if((px&0x00ffffffu)!=0)++sLit;
                                    unsigned ci=0;while(ci<sUsed && sCols[ci]!=px)++ci;
                                    if(ci<sUsed)++sColCnt[ci];
                                    else if(sUsed<4){sCols[sUsed]=px;sColCnt[sUsed]=1;++sUsed;}
                                }
                                uintptr_t dRow=dstBase+uint64_t(lx0)*dstStride+dstColOff;
                                for(uint32_t k=0;k<4;++k,dRow+=dstStride*2) {
                                    uint64_t *o0=reinterpret_cast<uint64_t *>(dRow);
                                    uint64_t *o1=reinterpret_cast<uint64_t *>(dRow+dstStride);
                                    const uint64_t r15=p[15][k],r14=p[14][k],r13=p[13][k],r12=p[12][k];
                                    const uint64_t r11=p[11][k],r10=p[10][k],r9=p[9][k],r8=p[8][k];
                                    o0[0]=((r15&kLo32)|(r14<<32))|kOpaqueAlpha;
                                    o0[1]=((r13&kLo32)|(r12<<32))|kOpaqueAlpha;
                                    o0[2]=((r11&kLo32)|(r10<<32))|kOpaqueAlpha;
                                    o0[3]=((r9&kLo32)|(r8<<32))|kOpaqueAlpha;
                                    o1[0]=((r15>>32)|(r14&kHi32))|kOpaqueAlpha;
                                    o1[1]=((r13>>32)|(r12&kHi32))|kOpaqueAlpha;
                                    o1[2]=((r11>>32)|(r10&kHi32))|kOpaqueAlpha;
                                    o1[3]=((r9>>32)|(r8&kHi32))|kOpaqueAlpha;
                                    const uint64_t r7=p[7][k],r6=p[6][k],r5=p[5][k],r4=p[4][k];
                                    const uint64_t r3=p[3][k],r2=p[2][k],r1=p[1][k],r0=p[0][k];
                                    o0[4]=((r7&kLo32)|(r6<<32))|kOpaqueAlpha;
                                    o0[5]=((r5&kLo32)|(r4<<32))|kOpaqueAlpha;
                                    o0[6]=((r3&kLo32)|(r2<<32))|kOpaqueAlpha;
                                    o0[7]=((r1&kLo32)|(r0<<32))|kOpaqueAlpha;
                                    o1[4]=((r7>>32)|(r6&kHi32))|kOpaqueAlpha;
                                    o1[5]=((r5>>32)|(r4&kHi32))|kOpaqueAlpha;
                                    o1[6]=((r3>>32)|(r2&kHi32))|kOpaqueAlpha;
                                    o1[7]=((r1>>32)|(r0&kHi32))|kOpaqueAlpha;
                                }
                            }
                        }
                        for(;ly0<height;ly0+=8) {
                            uint64_t rb[8];
                            for(uint32_t r=0;r<8;++r)rb[r]=uint64_t(ly0+r)*sourceStride;
                            const uint64_t dstColOff=uint64_t(physW-8-ly0)*4;
                            for(uint32_t lx0=0;lx0<width;lx0+=8) {
                                const uint64_t lxBytes=uint64_t(lx0)*4;
                                const uint64_t *p[8];
                                for(uint32_t r=0;r<8;++r) {
                                    const uint64_t bo=rb[r]+lxBytes;
                                    p[r]=reinterpret_cast<const uint64_t *>(sPageVa[bo>>12]+(bo&4095ULL));
                                }
                                uintptr_t dRow=dstBase+uint64_t(lx0)*dstStride+dstColOff;
                                for(uint32_t k=0;k<4;++k,dRow+=dstStride*2) {
                                    uint64_t *o0=reinterpret_cast<uint64_t *>(dRow);
                                    uint64_t *o1=reinterpret_cast<uint64_t *>(dRow+dstStride);
                                    const uint64_t r7=p[7][k],r6=p[6][k],r5=p[5][k],r4=p[4][k];
                                    const uint64_t r3=p[3][k],r2=p[2][k],r1=p[1][k],r0=p[0][k];
                                    o0[0]=((r7&kLo32)|(r6<<32))|kOpaqueAlpha;
                                    o0[1]=((r5&kLo32)|(r4<<32))|kOpaqueAlpha;
                                    o0[2]=((r3&kLo32)|(r2<<32))|kOpaqueAlpha;
                                    o0[3]=((r1&kLo32)|(r0<<32))|kOpaqueAlpha;
                                    o1[0]=((r7>>32)|(r6&kHi32))|kOpaqueAlpha;
                                    o1[1]=((r5>>32)|(r4&kHi32))|kOpaqueAlpha;
                                    o1[2]=((r3>>32)|(r2&kHi32))|kOpaqueAlpha;
                                    o1[3]=((r1>>32)|(r0&kHi32))|kOpaqueAlpha;
                                }
                            }
                        }
                    } else {
                        auto read8=[&](uint64_t byteOff,uint32_t out[8]){
                            const uint64_t pg=byteOff>>12;
                            const uint64_t inP=byteOff&4095ULL;
                            if(inP<=4064ULL) {
                                memcpy(out,sPageVa[pg]+inP,32);
                            } else {
                                const uint64_t a=4096ULL-inP;
                                memcpy(out,sPageVa[pg]+inP,size_t(a));
                                memcpy(reinterpret_cast<uint8_t *>(out)+a,sPageVa[pg+1],size_t(32ULL-a));
                            }
                        };
                        for(uint32_t lx0=0;lx0<width;lx0+=8) {
                            for(uint32_t ly0=0;ly0<height;ly0+=8) {
                                uint32_t tile[8][8];
                                for(uint32_t r=0;r<8;++r)
                                    read8(uint64_t(ly0+r)*sourceStride+uint64_t(lx0)*4,tile[r]);
                                if(doSample && (ly0&63)==32 && (lx0&63)==0) {
                                    const uint32_t px=tile[0][0];
                                    ++sTotal;
                                    if((px&0x00ffffffu)!=0)++sLit;
                                    unsigned ci=0;while(ci<sUsed && sCols[ci]!=px)++ci;
                                    if(ci<sUsed)++sColCnt[ci];
                                    else if(sUsed<4){sCols[sUsed]=px;sColCnt[sUsed]=1;++sUsed;}
                                }
                                const uint64_t dstColOff=uint64_t(physW-8-ly0)*4;
                                for(uint32_t c=0;c<8;++c) {
                                    volatile uint64_t *o64=reinterpret_cast<volatile uint64_t *>(
                                        dstBase+uint64_t(lx0+c)*dstStride+dstColOff);
                                    o64[0]=(uint64_t(tile[7][c])|(uint64_t(tile[6][c])<<32))|kOpaqueAlpha;
                                    o64[1]=(uint64_t(tile[5][c])|(uint64_t(tile[4][c])<<32))|kOpaqueAlpha;
                                    o64[2]=(uint64_t(tile[3][c])|(uint64_t(tile[2][c])<<32))|kOpaqueAlpha;
                                    o64[3]=(uint64_t(tile[1][c])|(uint64_t(tile[0][c])<<32))|kOpaqueAlpha;
                                }
                            }
                        }
                    }
                    if(doSample) {
                        uint64_t rotEnd=0,frq=19200000;
                        __asm__ volatile("isb\n\tmrs %0, cntpct_el0\n\tmrs %1, cntfrq_el0":"=r"(rotEnd),"=r"(frq));
                        if(!frq)frq=19200000;
                        IOLog("LQ102GPU COPY_SPLIT #%u flush_us=%llu rot_us=%llu stride=%llu\n",
                              fno,(unsigned long long)((rotStart-copyStart)*1000000ULL/frq),
                              (unsigned long long)((rotEnd-rotStart)*1000000ULL/frq),(unsigned long long)sourceStride);
                    }
                }
            } else {
                ok=(totalNeed<=memLen && dstStride>=rowBytes && dstStride*(height-1)+rowBytes<=bootMapping->getLength());
                uint64_t off=0;
                uint32_t y=0;
                uint64_t col=0;
                while(ok && y<height && off<totalNeed) {
                    IOByteCount segLen=0;
                    const addr64_t phys=memory->getPhysicalSegment(off,&segLen,kIOMemoryMapperNone);
                    if(!phys || !segLen){ok=false;break;}
                    const uint64_t useLen=(off+segLen>totalNeed)?(totalNeed-off):uint64_t(segLen);
                    const vm_offset_t srcVa=ml_static_ptovirt(vm_offset_t(phys));
                    if(!srcVa){ok=false;break;}
                    flush_dcache64((addr64_t)srcVa,(unsigned)useLen,false);
                    const uint8_t *sp=reinterpret_cast<const uint8_t *>(srcVa);
                    uint64_t rem=useLen;
                    while(rem>0 && y<height) {
                        if(col<rowBytes) {
                            uint64_t n=rowBytes-col;
                            if(n>rem)n=rem;
                            if(doSample && (y&63)==32) {
                                for(uint64_t k=0;k+4<=n;k+=64) {
                                    uint32_t px=0;memcpy(&px,sp+k,4);
                                    ++sTotal;
                                    if((px&0x00ffffffu)!=0)++sLit;
                                    unsigned ci=0;while(ci<sUsed && sCols[ci]!=px)++ci;
                                    if(ci<sUsed)++sColCnt[ci];
                                    else if(sUsed<4){sCols[sUsed]=px;sColCnt[sUsed]=1;++sUsed;}
                                }
                            }
                            uintptr_t dp=dstBase+uint64_t(y)*dstStride+col;
                            const uint8_t *cp=sp;
                            uint64_t cn=n;
                            if(((dp|cn)&7)==0) {
                                volatile uint64_t *o64=reinterpret_cast<volatile uint64_t *>(dp);
                                uint64_t q=cn>>3,i=0;
                                for(;i+4<=q;i+=4) {
                                    uint64_t a,b,c,d;
                                    memcpy(&a,cp,8);memcpy(&b,cp+8,8);memcpy(&c,cp+16,8);memcpy(&d,cp+24,8);
                                    o64[i]=a;o64[i+1]=b;o64[i+2]=c;o64[i+3]=d;
                                    cp+=32;
                                }
                                for(;i<q;++i){uint64_t a;memcpy(&a,cp,8);o64[i]=a;cp+=8;}
                            } else if(((dp|cn)&3)==0) {
                                volatile uint32_t *o32=reinterpret_cast<volatile uint32_t *>(dp);
                                for(uint64_t i=0,w=cn>>2;i<w;++i){uint32_t a;memcpy(&a,cp,4);o32[i]=a;cp+=4;}
                            } else {
                                volatile uint8_t *o8=reinterpret_cast<volatile uint8_t *>(dp);
                                for(uint64_t i=0;i<cn;++i)o8[i]=cp[i];
                            }
                            sp+=n;rem-=n;col+=n;
                        } else {
                            uint64_t skip=sourceStride-col;
                            if(skip>rem)skip=rem;
                            sp+=skip;rem-=skip;col+=skip;
                        }
                        if(col>=sourceStride){col-=sourceStride;++y;}
                    }
                    off+=useLen;
                }
            }
            memory->complete();
            if(!ok) {
                native_legacy_transfer_observed(kIOReturnBadArgument,request,0);return;
            }
            __asm__ volatile("dsb sy" ::: "memory");
            {uint64_t copyEnd;__asm__ volatile("isb\n\tmrs %0, cntpct_el0":"=r"(copyEnd));native_legacy_copy_timing_observed(copyEnd-copyStart,length);}
            if(doSample) {
                IOLog("LQ102GPU FRAME #%u lit=%u/%u c=%x(%u),%x(%u),%x(%u),%x(%u)\n",
                      fno,sLit,sTotal,sCols[0],sColCnt[0],sCols[1],sColCnt[1],sCols[2],sColCnt[2],sCols[3],sColCnt[3]);
            }
            shadowValid=false;transferred=true;
            native_legacy_transfer_observed(kIOReturnSuccess,request,length);
            if(useDb) {
                dbPendingBuf=nextBuf;dbLatchRequest=request;dbLatchStart=mach_absolute_time();
                dbFlip(nextBuf);
                dbLatchTimer->setTimeoutUS(500);
                return;
            }
            finishTransfer(request);
            return;
        }
        dbResetToBuf0();
        // Surfaces may be write-combined (iPadOS 27 display surfaces are): reading them uncached costs seconds per frame. Read through
        // a cacheable view, after cleaning and invalidating it so lines from the previous frame are not reused.
        IOMemoryMap *source=memory->map(kIOMapAnywhere|kIOMapReadOnly|kIOMapCopybackCache);
        if(!source || !source->getVirtualAddress() || source->getLength()<allocation) {
            OSSafeReleaseNULL(source);native_legacy_transfer_observed(kIOReturnNoMemory,request,0);return;
        }
        flush_dcache64((addr64_t)source->getVirtualAddress(),(unsigned)source->getLength(),false);
        if(half) {
            if(!native_legacy_prepare_scanout()) {OSSafeReleaseNULL(source);native_legacy_transfer_observed(kIOReturnNotReady,request,0);return;}
            uint64_t copyStart;__asm__ volatile("isb\n\tmrs %0, cntpct_el0":"=r"(copyStart));
            if(!convertHalfRows(reinterpret_cast<volatile void *>(bootMapping->getVirtualAddress()),bootMapping->getLength(),video.v_rowBytes,
                reinterpret_cast<const void *>(source->getVirtualAddress()),source->getLength(),sourceStride,width,height)) {
                OSSafeReleaseNULL(source);native_legacy_transfer_observed(kIOReturnBadArgument,request,0);return;
            }
            __asm__ volatile("dsb sy" ::: "memory");
            {uint64_t copyEnd;__asm__ volatile("isb\n\tmrs %0, cntpct_el0":"=r"(copyEnd));native_legacy_copy_timing_observed(copyEnd-copyStart,length);}
            shadowValid=false;OSSafeReleaseNULL(source);transferred=true;
            native_legacy_transfer_observed(kIOReturnSuccess,request,length);
            finishTransfer(request);
            return;
        }
        if(!native_legacy_copy_layout(reinterpret_cast<volatile void *>(bootMapping->getVirtualAddress()),
            bootMapping->getLength(),video.v_rowBytes,reinterpret_cast<const void *>(source->getVirtualAddress()),
            source->getLength(),sourceStride,width,height)) {
            OSSafeReleaseNULL(source);native_legacy_transfer_observed(kIOReturnBadArgument,request,0);return;
        }
        if(!native_legacy_prepare_scanout()) {
            OSSafeReleaseNULL(source);native_legacy_transfer_observed(kIOReturnNotReady,request,0);return;
        }
        uint64_t copyStart;__asm__ volatile("isb\n\tmrs %0, cntpct_el0":"=r"(copyStart));
        uint64_t stored=UINT64_MAX;
        {
            // Store only what changed since the previous frame (the scanout memory is slow device memory).
            uint64_t need=(uint64_t)width*height*4;
            // Differential copy is opt-in (fb-diff=1): on hardware it reads the whole source every frame and was not faster
            // than the plain copy (143-285 ms per swap either way), and the first boots with it were followed by an unresponsive
            // lock screen that disappeared with the plain copy (int-005).
            static int diffOff=-1;
            if(diffOff<0){unsigned v=0;PE_parse_boot_argn("fb-diff",&v,sizeof v);diffOff=(v!=1);}
            if(!diffOff && !shadow && need<=(64ull<<20)){shadow=IOMallocAligned((vm_size_t)need,16384);if(shadow){shadowBytes=need;shadowValid=false;}}
            if(!diffOff && shadow && shadowBytes>=need)
                stored=native_legacy_copy_diff(reinterpret_cast<volatile void *>(bootMapping->getVirtualAddress()),
                    bootMapping->getLength(),video.v_rowBytes,reinterpret_cast<const void *>(source->getVirtualAddress()),
                    source->getLength(),sourceStride,width,height,shadow,shadowValid);
            if(stored!=UINT64_MAX)shadowValid=true;
        }
        if(stored==UINT64_MAX) {
            shadowValid=false;
            if(!native_legacy_copy_pixels(reinterpret_cast<volatile void *>(bootMapping->getVirtualAddress()),
                bootMapping->getLength(),video.v_rowBytes,reinterpret_cast<const void *>(source->getVirtualAddress()),
                source->getLength(),sourceStride,width,height)) {
                OSSafeReleaseNULL(source);native_legacy_transfer_observed(kIOReturnBadArgument,request,0);return;
            }
            stored=length;
        }
        __asm__ volatile("dsb sy" ::: "memory");
        {uint64_t copyEnd;__asm__ volatile("isb\n\tmrs %0, cntpct_el0":"=r"(copyEnd));native_legacy_copy_timing_observed(copyEnd-copyStart,stored);}
        OSSafeReleaseNULL(source);transferred=true;
        native_legacy_transfer_observed(kIOReturnSuccess,request,length);
        finishTransfer(request);
    }
    // The GPU client reported its copy (status 0) or lost it. Success retires the swap like a finished copy; anything else uses the CPU copy.
    void finishGpuSwap(int status) {
        const OriginalLegacySwapRequest *request=gpuRequest;
        if(!request)return;
        gpuRequest=nullptr;
        if(gpuRetired) {
            // The swap retired when the client took it; its copy ending only releases the next frame. A failed copy loses this frame
            // (the next one takes the CPU copy).
            gpuRetired=false;
            if(status==0)native_legacy_transfer_observed(kIOReturnSuccess,request,gpuLength);
            else {native_legacy_early_failures=native_legacy_early_failures+1;native_legacy_gpu_fallback_observed(status);gpuBypass=true;}
            transferred=false;kickSwapQueue();return;
        }
        if(status==0) {
            native_legacy_transfer_observed(kIOReturnSuccess,request,gpuLength);
            finishTransfer(request,true);return;
        }
        native_legacy_gpu_fallback_observed(status);
        transferred=false;gpuBypass=true;kickSwapQueue();
    }
    // Hands the pending head to the unchanged family's completion. Leaves transferred alone: the callers decide when the next frame may go.
    bool retireSwap(const OriginalLegacySwapRequest *request,bool force) {
        unsigned retire=0,cpuPresent=0;
        PE_parse_boot_argn("offline-legacy-retire",&retire,sizeof(retire));
        PE_parse_boot_argn("offline-legacy-cpu-present",&cpuPresent,sizeof(cpuPresent));
        if(!(retire==1 || cpuPresent==1 || force))return false;
        if(!activateOnlyPendingSwap(request))return false;
        stat(11);note(6,-1,request);
        removeValidated(request);
        IOMobileFramebufferLegacy::completeCurrentSwap();
        native_legacy_retirement_observed(this);
        return true;
    }
    // Separately gated retirement after a real scanout store, shared by copied and blank frames.
    void finishTransfer(const OriginalLegacySwapRequest *request,bool force=false) {
        // Only after the real copy and store barrier: select the actual pending head and let the unchanged family release it and wake
        // waiters. This reports memory scanout completion, not a panel vblank or hardware fence.
        if(!retireSwap(request,force))return;
        // The unchanged family has retired this generation and released its current reference. Permit the next independently validated
        // single pending frame. Keep the latch set while completion can reenter this method, and whenever retirement remains disabled.
        transferred=false;
        kickSwapQueue();
    }
#if defined(NATIVE_LEGACY_CANCEL_SWAPS) && NATIVE_LEGACY_CANCEL_SWAPS
    // swap_wait_gated gives up on a swap that has not completed in 5 s ("CommandWake didn't happen even after 5 seconds ... cancelling
    // swaps") and calls this first, then cancels its own queue. Forget the swaps this class tracks: a GPU copy that ends later finds no
    // request (finishGpuSwap), a request the family cancelled is no longer its queue's head, so nothing completes twice and the next
    // frame is not held behind the cancelled one. The family only logs the result; the slot used to be a guard that panicked.
    bool cancelSwapsAfterTimeout() override {
        const uint32_t n=bumpCall(13);
        if(n<=8)IOLog("LQ102GPU NLD cancelSwapsAfterTimeout #%u\n",n);
        native_legacy_swap_timeouts=native_legacy_swap_timeouts+1;
        if(fenceTimer)fenceTimer->cancelTimeout();
        if(dbLatchTimer)dbLatchTimer->cancelTimeout();
        dbLatchRequest=nullptr;
        fenceFor=nullptr;fenceTarget=0;fenceSince=0;fenceCaptured=false;fenceSlow=false;traceGpuComplete=false;
        for(auto &entry: validated)entry=nullptr;
        gpuRequest=nullptr;gpuRetired=false;transferred=false;
#if defined(NATIVE_LEGACY_MACOS) && NATIVE_LEGACY_MACOS
        // macOS names this slot are_timings_enabled: disp_has_no_clients_gated reprograms the display with a dummy swap when it is
        // true. The virtual-machine display answers false, as a display with no timing generator does.
        return false;
#else
        return true;
#endif
    }
#endif
#if defined(NATIVE_LEGACY_MACOS) && NATIVE_LEGACY_MACOS
    // macOS: the family calls this slot (notify_swap_done_gated) as the current swap completes. Its swap info goes to the clients
    // that asked for it (swap_info_notify_dispatch_gated, which calls doSwapInfoNotify per request) unless notifications are held,
    // then the held ones go first. Layout and words as the virtual-machine display fills them: swap ID, then the family's swap time,
    // 0, and the swap's two completion words.
    struct SwapInfo {uint32_t swapID,pad;uint64_t words[5];};
    static_assert(sizeof(SwapInfo)==48,"IOMobileFramebufferLegacy::SwapInfoBlob");
    static constexpr unsigned kSwapInfoRing=6;
    SwapInfo swapInfo[kSwapInfoRing];   // no initializers: IOKit objects are allocated zeroed (see validatedAt)
    unsigned swapInfoRead,swapInfoWrite;
    IOReturn collectCompletionReports(uint32_t swapID,void *,uint32_t *,uint32_t) override {
        auto self=reinterpret_cast<unsigned char *>(this);
        const unsigned char *swap=nullptr;memcpy(&swap,self+kLegacyCurrentSwap,sizeof(swap));
        uint32_t dropped=0;
        if(swap)memcpy(&dropped,swap+kRequestDropReasons,4);
        if(!swap || dropped)return kIOReturnUnsupported;
        SwapInfo &info=swapInfo[swapInfoWrite];
        info={};info.swapID=swapID;
        memcpy(&info.words[0],self+kLegacySwapInfoTime,8);
        memcpy(&info.words[2],swap+kRequestSwapInfoA,8);
        uint32_t second=0;memcpy(&second,swap+kRequestSwapInfoB,4);info.words[3]=second;
        uint16_t held=0;memcpy(&held,self+kLegacySwapInfoHeld,2);
        if(held){swapInfoWrite=(swapInfoWrite+1)%kSwapInfoRing;return kIOReturnSuccess;}
        for(;swapInfoRead!=swapInfoWrite;swapInfoRead=(swapInfoRead+1)%kSwapInfoRing)native_legacy_swap_info_dispatch(this,&swapInfo[swapInfoRead]);
        native_legacy_swap_info_dispatch(this,&info);
        return kIOReturnSuccess;
    }
    // The client's async result: the mask, the swap ID and each word the mask asks for (word 1 is the time since its previous
    // notification), as 64-bit values or, with mask bit 31, 32-bit halves; at most 12 values.
    IOReturn doSwapInfoNotify(void *request,const void *blob) override {
        auto r=static_cast<unsigned char *>(request);
        auto info=static_cast<const SwapInfo *>(blob);
        uint32_t mask=0;memcpy(&mask,r+kNotifyMask,4);
        uint64_t last=0;memcpy(&last,r+kNotifyLastTime,8);
        io_user_reference_t args[12]={mask,info->swapID};
        unsigned count=2;
        for(unsigned word=0;word<5;++word) {
            if(!(mask>>word&1))continue;
            const uint64_t value=word==1?info->words[0]-last:info->words[word];
            const unsigned need=mask>>31?2:1;
            if(count+need>12){IOLog("IOMFB Packer put: ran out of space\n");continue;}
            if(need==2){args[count++]=uint32_t(value);args[count++]=value>>32;}
            else args[count++]=value;
        }
        memcpy(r+kNotifyLastTime,&info->words[0],8);
        return nativeSendAsyncResult(reinterpret_cast<io_user_reference_t *>(r+kNotifyAsyncReference),kIOReturnSuccess,args,count,
                                     kIOUserNotifyOptionCanDrop);
    }
    // Swap info notifications (type 3) keep their word mask in the request; the display has no other notification type.
    IOReturn setNotifyTagMaskGated(uint32_t type,void *request,uint32_t mask) override {
        const uint32_t n=bumpCall(14);
        if(n<=8)IOLog("LQ102GPU NLD setNotifyTagMaskGated(type=%u, mask=0x%x)\n",type,mask);
        if(type!=3)return kIOReturnBadArgument;
        memcpy(static_cast<unsigned char *>(request)+kNotifyMask,&mask,4);return kIOReturnSuccess;
    }
    // No factory calibration, frame-info trace or CRC on a GOP scanout.
    IOReturn factoryPortal(void *,task_t) override {return kIOReturnUnsupported;}
    IOReturn executeFactoryConfigurations() override {return kIOReturnUnsupported;}
    IOReturn setFrameInfoNotificationState(void *,bool on) override {
        const uint32_t n=bumpCall(15);
        if(n<=8)IOLog("LQ102GPU NLD setFrameInfoNotificationState(%u)\n",(unsigned)on);
        return kIOReturnSuccess;
    }
    IOReturn notifyCrcReady(uint32_t) override {return kIOReturnSuccess;}
#else
    IOReturn collectCompletionReports(uint32_t,void *,uint32_t *count,uint32_t) override {
        // The original completion helper passes null optional outputs and
        // ignores this IOReturn. GOP exposes no hardware completion telemetry.
        if(count)*count=0;
        return kIOReturnUnsupported;
    }
#endif
#if defined(NATIVE_LEGACY_MACOS) && NATIVE_LEGACY_MACOS
    bool consoleReleased=false;
#endif
    bool validateSwap(const OriginalLegacySwapRequest *request) override {
        // Qualified original request fields are packed; use memcpy for each
        // access. Accept only one full-frame, untransformed, nonplanar BGRA
        // surface with real original backing memory. No generic capability
        // or success is supplied for other layer/format/geometry contracts.
        auto bytes=reinterpret_cast<const unsigned char *>(request);
        auto word=[&](unsigned offset){uint32_t value=0;memcpy(&value,bytes+offset,4);return value;};
        OSObject *surface=nullptr;unsigned reason=1;bool accepted=false;
        unsigned enabled=0;PE_parse_boot_argn("offline-legacy-validate",&enabled,sizeof(enabled));
        if(enabled==1 && logicalPM && primary && bootMapping && request) {
            reason=2;OSObject *surfaces[4]={};memcpy(surfaces,bytes+kRequestSurfaces,sizeof(surfaces));surface=surfaces[0];
            uint32_t width=0,height=0;getDisplayDimensions(&width,&height);
            if(surface && surface->metaCast("IOSurface") && !surfaces[1] && !surfaces[2] && !surfaces[3] &&
               native_legacy_single_layer_state(word(kRequestMasks),word(kRequestMasks+4),word(kRequestMasks+8))) {
                reason=3;bool rectangles=true;
                const unsigned rectOffsets[]={kRequestRect0,kRequestRect1};
                for(unsigned offset: rectOffsets) {
                    uint32_t rect[4]={};memcpy(rect,bytes+offset,sizeof(rect));
                    rectangles=rectangles && rect[0]==0 && rect[1]==0 && rect[2]==width && rect[3]==height;
                }
                bool options=true;for(unsigned offset=kRequestOptions;offset<=kRequestOptions+8;offset+=4)options=options && word(offset)==0;
                if(width && height && rectangles && options && word(kRequestDims)==width && word(kRequestDims+4)==height) {
                    reason=4;
                    IOMemoryDescriptor *memory=native_legacy_surface_descriptor(surface);
                    // A surface larger than the display (rows or lines padded to the GPU's alignment) is accepted: only the visible rectangle,
                    // which the request's rectangles already name as the whole display, is copied.
                    if(native_legacy_surface_width(surface)>=width && native_legacy_surface_height(surface)>=height &&
                       nativeScanoutFormat(native_legacy_surface_format(surface),native_legacy_surface_planes(surface)) &&
                       memory && memory->metaCast("IOMemoryDescriptor") &&
                       native_legacy_surface_bounds(width,height,native_legacy_surface_stride(surface),
                           native_legacy_surface_allocation(surface),memory->getLength())) {
                        reason=0;accepted=true;
                    } else {
                        native_legacy_surface_rejected(native_legacy_surface_width(surface),native_legacy_surface_height(surface),
                            native_legacy_surface_format(surface),native_legacy_surface_planes(surface),native_legacy_surface_stride(surface),
                            native_legacy_surface_allocation(surface),memory?memory->getLength():0);
                    }
                }
            }
        }
        if(!accepted && reason==2 && !surface && enabled==1) {
            // No surface in any slot and every updated layer disabled over black: present a blank screen.
            OSObject *none[4]={};memcpy(none,bytes+kRequestSurfaces,sizeof(none));
            uint32_t width=0,height=0;getDisplayDimensions(&width,&height);
            bool options=true;for(unsigned offset=kRequestOptions;offset<=kRequestOptions+8;offset+=4)options=options && word(offset)==0;
            if(!none[0] && !none[1] && !none[2] && !none[3] && width && height && options &&
               word(kRequestDims)==width && word(kRequestDims+4)==height && native_legacy_blank_state(word(kRequestMasks),word(kRequestMasks+4),word(kRequestMasks+8))) {
                reason=5;accepted=true;
            }
        }
        if(accepted){
            // The OS's compositor now owns the panel: the kernel console stops drawing into the framebuffer and stays on the serial
            // console, as IOFramebuffer does when the window server takes a Mac's display over. With vc-text=1 (text console on the
            // boot framebuffer), console lines kept landing over the compositor's frames (macOS run35).
#if defined(NATIVE_LEGACY_MACOS) && NATIVE_LEGACY_MACOS
            if(!consoleReleased){consoleReleased=true;if(liuqin_fb_suspend)liuqin_fb_suspend(1);PE_initialize_console(nullptr,kPEDisableScreen);}
#endif
            addValidated(request);stat(0);note(1,-1,request);const unsigned depth=validatedCount();if(depth>native_legacy_swapstat[15])native_legacy_swapstat[15]=depth;}
        else removeValidated(request);
        const uint32_t vn=bumpCall(11);
        if(vn<=8)IOLog("LQ102GPU NLD validateSwap #%u acc=%u reason=%u dims=%ux%u\n",vn,(unsigned)accepted,reason,word(kRequestDims),word(kRequestDims+4));
        native_legacy_swap_validation_observed(accepted,reason,request,surface);return accepted;
    }
    // The original slot-188 caller passes a uint32_t output and consumes an
    // IOReturn. Its implementation assumes an AppleARMIODevice provider.
    // Query our actual generic provider instead; GOP supplies no dot pitch.
    IOReturn getDotPitch(uint32_t *pitch) override {
        const uint32_t n=bumpCall(7);
        if(!pitch)return kIOReturnBadArgument;
        *pitch=0;IOService *provider=getProvider();if(!provider)return kIOReturnNotReady;
        OSObject *property=provider->getProperty("dot-pitch");
        if(!property)return kIOReturnNotFound;
        OSData *data=OSDynamicCast(OSData,property);
        if(!data || data->getLength()!=sizeof(*pitch))return kIOReturnBadArgument;
        memcpy(pitch,data->getBytesNoCopy(),sizeof(*pitch));
        if(n<=4)IOLog("LQ102GPU NLD getDotPitch -> %u\n",*pitch);
        return kIOReturnSuccess;
    }
    // Selector 74 enumerates optional frame-info trace keys, not display
    // modes. This backend implements no trace-key subscription contract.
    IOReturn supportedFrameInfo(uint32_t idx,uint32_t *count,char *key,uint32_t *mask) override {
        const uint32_t n=bumpCall(8);
        if(n<=4)IOLog("LQ102GPU NLD supportedFrameInfo(%u)\n",idx);
        if(!count || !key || !mask)return kIOReturnBadArgument;
        *count=0;*mask=0;bzero(key,64);return kIOReturnUnsupported;
    }
    IOReturn newUserClient(task_t task,void *security,UInt32 type,IOUserClient **client) override {
        const uint32_t n=bumpCall(0);
        native_legacy_client_enter(task,type);
        IOReturn status=IOMobileFramebufferLegacy::newUserClient(task,security,type,client);
        if(n<=12)IOLog("LQ102GPU NLD newUserClient #%u type=%u status=0x%x\n",n,(unsigned)type,(unsigned)status);
        native_legacy_client_observed(status,status==kIOReturnSuccess && client?*client:nullptr);return status;
    }
    bool startHardware() override {
        unsigned enabled=0;
        PE_parse_boot_argn("offline-legacy-gop",&enabled,sizeof(enabled));
        if(enabled!=1)return false;
        PE_Video video={};IOService *provider=getProvider();
        if(!provider || PE_current_console(&video) || !video.v_baseAddr ||
           !video.v_width || !video.v_height || video.v_depth!=32 || video.v_rotate ||
           video.v_width>16384 || video.v_height>16384 || video.v_rowBytes<video.v_width*4 ||
           video.v_rowBytes>UINT64_MAX/video.v_height)return false;
        // Scanout lives in reserved splash DRAM (0xb8000000); Normal Non-Cacheable write-combining
        // avoids 22-93 ms Device-nGnRnE per-store stalls while keeping writes immediately visible to DPU.
        IOMemoryMap *mapping=provider->mapDeviceMemoryWithIndex(0,kIOMapWriteCombineCache);
        if(!mapping)mapping=provider->mapDeviceMemoryWithIndex(0,kIOMapInhibitCache);
        if(!mapping)return false;
        bool valid=mapping->getVirtualAddress() && mapping->getPhysicalAddress()==video.v_baseAddr &&
                   mapping->getLength()==video.v_rowBytes*video.v_height;
        if(valid) {
            // Expose landscape 2880x1800 (1440x900 @2x Retina) by default when physical GOP is portrait (1800x2880);
            // kickOnce performs a cache-tiled 90-degree CCW rotate onto the physical panel.
            const bool landscape=(video.v_width<video.v_height);
            const uint32_t logW=landscape?(uint32_t)video.v_height:(uint32_t)video.v_width;
            const uint32_t logH=landscape?(uint32_t)video.v_width:(uint32_t)video.v_height;
            installBootDimensions(logW,logH);
            uint32_t width=0,height=0;getDisplayDimensions(&width,&height);
            valid=width==logW && height==logH;
            if(valid) {
                OSSafeReleaseNULL(bootMapping);bootMapping=mapping;mapping=nullptr;primary=video.v_display==1;
                valid=native_legacy_gop_mapping_observed(this,bootMapping,(uint32_t)video.v_width,(uint32_t)video.v_height);
#if defined(NATIVE_LEGACY_DEFAULT_SURFACE) && NATIVE_LEGACY_DEFAULT_SURFACE
                // The family calls its void slot 316 after startHardware. Our backend supplies the client's default surface.
                if(valid)valid=installDefaultSurface(width,height);
#endif
#if defined(NATIVE_LEGACY_MACOS) && NATIVE_LEGACY_MACOS
                if(valid && !publishDisplayAttributes(width,height))IOLog("NativeLegacyDisplay: display attributes not published\n");
                if(valid)publishDisplayContainer(width,height);
                // The panel is always connected: reported plugged in, as Apple's virtual-machine display does in start_hardware. While the
                // state stays unplugged, WindowServer keeps this display disabled and composites a virtual main display (macOS-DroidVM).
                if(valid){
                    gLiveDisplay=this;
                    native_legacy_hotplug_notify(this,1);
                    IOLog("LQ102GPU NLD startHardware ok %ux%u primary=%u vdisp=%lu hp=%u vsync=%u pmap=0x%x\n",
                          width,height,(unsigned)primary,(unsigned long)video.v_display,
                          native_legacy_hotplug_state(),native_legacy_refresh_hz(),
                          pmap_cache_attributes(unsigned(bootMapping->getPhysicalAddress()>>12)));
                }
#endif
            }
        }
        OSSafeReleaseNULL(mapping);return valid;
    }
#if defined(NATIVE_LEGACY_MACOS) && NATIVE_LEGACY_MACOS
    static bool putNumber(OSDictionary *d,const char *key,uint64_t value,unsigned bits=32) {
        OSNumber *n=OSNumber::withNumber(value,bits);bool ok=n && d->setObject(key,n);OSSafeReleaseNULL(n);return ok;
    }
    static bool putString(OSDictionary *d,const char *key,const char *value) {
        OSString *v=OSString::withCString(value);bool ok=v && d->setObject(key,v);OSSafeReleaseNULL(v);return ok;
    }
    static OSDictionary *point(uint32_t x,uint32_t y) {
        OSDictionary *d=OSDictionary::withCapacity(3);
        if(d && (!putNumber(d,"X",x) || !putNumber(d,"Y",y)))OSSafeReleaseNULL(d);
        return d;
    }
    static bool putPoint(OSDictionary *d,const char *key,uint32_t x,uint32_t y) {
        OSDictionary *v=point(x,y);bool ok=v && d->setObject(key,v);OSSafeReleaseNULL(v);return ok;
    }
    // The display as macOS reads it: one timing element and one color element, the display attributes, the transport and the
    // source and scaling limits, as the virtual-machine display (AppleParavirtDisplay) publishes them for its single mode.
    // What is measured: the active size is the GOP mode this backend scans out, the refresh rate is the rate of its own refresh
    // tick (vsync=, 60 by default). What is derived: the blanking, from the CVT reduced-blanking rule for that size (a GOP display
    // has no timing generator), and the pixel clock from it. The color element is 8-bit RGB SDR with sRGB chromaticities. The
    // physical size comes only from the provider's dot pitch; without one it is left out, as no panel size is known here.
    bool publishDisplayAttributes(uint32_t width,uint32_t height) {
        unsigned prefHz=effectiveRefreshHz();
        static const struct {uint64_t id; unsigned hz;} kModes[3]={
            {kDisplayTiming120,120u}, {kDisplayTiming144,144u}, {kDisplayTiming60,60u},
        };
        uint32_t hTotal=width+160,vTotal=height+23;
        auto makeTiming=[&](unsigned hz,uint64_t id,uint32_t score)->OSObject *{
            uint8_t timingData[80]={};
            auto word=[&](unsigned offset,uint32_t value){memcpy(timingData+offset,&value,4);};
            word(4,hTotal);word(8,width);word(12,32);word(16,80);word(20,48);word(28,1);
            word(36,vTotal);word(40,height);word(44,6);word(48,14);word(52,3);word(56,hz<<16);
            word(68,(uint32_t)((uint64_t)hTotal*vTotal*hz));
            OSObject *t=native_legacy_ioav_timing(timingData,2,4);
            if(t) {
                auto base=reinterpret_cast<uint8_t *>(t);
                memcpy(base+kIOAVElementID,&id,8);memcpy(base+kIOAVElementScore,&score,4);
            }
            return t;
        };
        OSObject *color=native_legacy_ioav_color(2,8,0,0,0,16,false,nullptr,nullptr,nullptr,nullptr);
        OSDictionary *attributes=OSDictionary::withCapacity(16),*product=OSDictionary::withCapacity(8),*chromaticity=OSDictionary::withCapacity(3);
        OSDictionary *white=point(20493,21561),*transport=OSDictionary::withCapacity(2),*source=OSDictionary::withCapacity(8),*scaling=OSDictionary::withCapacity(2);
        OSArray *colors=OSArray::withCapacity(1),*timings=OSArray::withCapacity(3),*timingColors=OSArray::withCapacity(1);
        OSObject *timingObjs[3]={nullptr,nullptr,nullptr};
        bool done=false;
        do {
            if(!color || !attributes || !product || !chromaticity || !white || !transport || !source || !scaling ||
               !colors || !timings || !timingColors)break;
            {
                auto base=reinterpret_cast<uint8_t *>(color);
                uint64_t cid=kDisplayColorID;uint32_t cscore=(uint32_t)cid;
                memcpy(base+kIOAVElementID,&cid,8);memcpy(base+kIOAVElementScore,&cscore,4);
            }
            if(!colors->setObject(color) || !timingColors->setObject(color))break;
            bool modesOk=true;
            for(unsigned i=0;i<3;++i) {
                const uint32_t score=(kModes[i].hz==prefHz)?2000u:(kModes[i].hz==144u?1500u:1000u);
                timingObjs[i]=makeTiming(kModes[i].hz,kModes[i].id,score);
                if(!timingObjs[i] || !timings->setObject(timingObjs[i])){modesOk=false;break;}
                native_legacy_ioav_timing_colors(timingObjs[i],timingColors);
            }
            if(!modesOk)break;
            if(!putString(product,"ManufacturerID","UNX") || !putNumber(product,"ProductID",0) || !putNumber(product,"SerialNumber",0) ||
               !putString(product,"ProductName","UniXNU Display"))break;
            if(!putPoint(chromaticity,"Red",41943,21627) || !putPoint(chromaticity,"Green",19661,39322) ||
               !putPoint(chromaticity,"Blue",9830,3932) || !putNumber(white,"Gamma",144179))break;
            if(!attributes->setObject("SupportsPQEOTF",kOSBooleanFalse) || !attributes->setObject("ProductAttributes",product) ||
               !attributes->setObject("Chromaticity",chromaticity) || !attributes->setObject("DefaultColorSpaceIsSRGB",kOSBooleanTrue) ||
               !attributes->setObject("DefaultWhitePoint",white) || !attributes->setObject("SupportsStandby",kOSBooleanTrue) ||
               !putNumber(attributes,"ContinuousFrequencySupport",3) ||
               !putNumber(attributes,"NativeFormatHorizontalPixels",width) || !putNumber(attributes,"NativeFormatVerticalPixels",height) ||
               !putNumber(attributes,"PreciseAspectRatio",((uint64_t)width<<16)/height))break;
            uint32_t pitch=0;
            if(getDotPitch(&pitch)==kIOReturnSuccess && pitch) {
                // Dot pitch in dots per inch; image size in centimetres.
                if(!putNumber(attributes,"MaxHorizontalImageSize",(width*254ULL/pitch+50)/100) ||
                   !putNumber(attributes,"MaxVerticalImageSize",(height*254ULL/pitch+50)/100))break;
            }
            if(!putString(transport,"Upstream","Other") || !putString(transport,"Downstream","Other"))break;
            if(!putNumber(source,"MaxSrcBufferWidth",16384) || !putNumber(source,"MaxSrcBufferHeight",16384) ||
               !putNumber(source,"MaxSrcRectWidth",8192) || !putNumber(source,"MaxSrcRectTotal",0) ||
               !putNumber(source,"IOMFBMaxCompressedSizeInBytes",0) ||
               !putNumber(source,"IOMFBCompressionSupport",0) ||
               !putNumber(source,"IOMFBAsyncRGBCompressionSupport",0))break;
            if(!putNumber(scaling,"RGBLayer_MinScaleFraction",4) || !putNumber(scaling,"RGBLayer_MaxScale",4))break;
            done=setProperty("DisplayAttributes",attributes) && setProperty("Transport",transport) && setProperty("ColorElements",colors) &&
                 setProperty("TimingElements",timings) && setProperty("IOMFBMaxSrcPixels",source) && setProperty("IOMFBScalingLimits",scaling);
        } while(false);
        OSSafeReleaseNULL(attributes);OSSafeReleaseNULL(product);OSSafeReleaseNULL(chromaticity);OSSafeReleaseNULL(white);
        OSSafeReleaseNULL(transport);OSSafeReleaseNULL(source);OSSafeReleaseNULL(scaling);OSSafeReleaseNULL(colors);
        OSSafeReleaseNULL(timings);OSSafeReleaseNULL(timingColors);OSSafeReleaseNULL(color);
        for(unsigned i=0;i<3;++i)OSSafeReleaseNULL(timingObjs[i]);
        return done;
    }
    // The display's container identifier, as macOS ties a touch screen to its display: WindowServer (WSHIDDisplayEventListener) takes
    // a digitizer's kUSBContainerID string as a UUID and finds the display whose CoreDisplay container ID equals it
    // (CGXDisplayDeviceWithContainerID). CoreDisplay reads that ID (IODisplayCreateInfoDictionary, "ContainerID") from the IODisplayEDID of
    // the first IODisplay at or below the display's service: the Container ID data block (tag 0x29, revision 0, 16 bytes) of a
    // DisplayID extension (tag 0x70). So a display object of the original IOGraphicsFamily class, never started or registered (no
    // IOGraphics display behavior), sits below this framebuffer with a 256-byte EDID: a base block describing the scanned-out mode
    // (the same derived timing as the timing element) and that extension. The touch screen (ShengHidInput) publishes the same UUID.
    static void containerID(uint8_t uuid[16]) {
        // FNV-1a of /chosen/unique-chip-id, then of the label; name-based (version 5 bits), RFC 4122 variant. The touch device makes it the
        // same way (NativeHidInput.cpp); without a chip id both use the label alone.
        uint64_t seed=0;
        if(IORegistryEntry *chosen=IORegistryEntry::fromPath("/chosen",gIODTPlane)) {
            OSData *id=OSDynamicCast(OSData,chosen->getProperty("unique-chip-id"));
            if(id && id->getLength()>=sizeof(seed))memcpy(&seed,id->getBytesNoCopy(),sizeof(seed));
            chosen->release();
        }
        static const char label[]="builtin-display-container";
        uint64_t h=0xcbf29ce484222325ull;
        for(unsigned i=0;i<8;++i)h=(h^((seed>>(8*i))&0xff))*0x100000001b3ull;
        for(unsigned half=0;half<2;++half) {
            for(const char *c=label;*c;++c)h=(h^(uint8_t)*c)*0x100000001b3ull;
            h=(h^half)*0x100000001b3ull;
            for(unsigned i=0;i<8;++i)uuid[half*8+i]=(uint8_t)(h>>(8*i));
        }
        uuid[6]=(uint8_t)((uuid[6]&0x0f)|0x50);uuid[8]=(uint8_t)((uuid[8]&0x3f)|0x80);
    }
    void publishDisplayContainer(uint32_t width,uint32_t height) {
        uint8_t edid[256]={};
        static const uint8_t header[8]={0x00,0xff,0xff,0xff,0xff,0xff,0xff,0x00};
        memcpy(edid,header,8);
        edid[8]=0x55;edid[9]=0xd8;            // manufacturer "UNX", as the display attributes' ManufacturerID
        edid[10]=0x01;                         // product 1
        edid[17]=2026-1990;edid[18]=1;edid[19]=4;   // EDID 1.4
        edid[20]=0xa0;                         // digital, 8 bits per color
        uint32_t pitch=0;
        uint32_t widthMm=0,heightMm=0;
        if(getDotPitch(&pitch)==kIOReturnSuccess && pitch){widthMm=(uint32_t)(width*254ULL/pitch/10);heightMm=(uint32_t)(height*254ULL/pitch/10);}
        edid[21]=(uint8_t)((widthMm+5)/10>255?255:(widthMm+5)/10);edid[22]=(uint8_t)((heightMm+5)/10>255?255:(heightMm+5)/10);
        edid[23]=120;                          // gamma 2.2
        edid[24]=0x02;                         // RGB 4:4:4; the preferred timing is the native mode
        static const uint8_t srgb[10]={0xee,0x91,0xa3,0x54,0x4c,0x99,0x26,0x0f,0x50,0x54};
        memcpy(edid+25,srgb,10);
        for(unsigned i=38;i<54;++i)edid[i]=0x01;   // no standard timings
        // Detailed timing: the derived reduced-blanking timing of publishDisplayAttributes (blanking 160 x 23, sync 32 x 6, front 48 x 3).
        unsigned hz=effectiveRefreshHz();
        const uint32_t hBlank=160,vBlank=23,hFront=48,hSync=32,vFront=3,vSync=6;
        uint64_t clock=(uint64_t)(width+hBlank)*(height+vBlank)*hz/10000;if(clock>0xffff)clock=0xffff;
        uint8_t *d=edid+54;
        d[0]=(uint8_t)clock;d[1]=(uint8_t)(clock>>8);
        d[2]=(uint8_t)width;d[3]=(uint8_t)hBlank;d[4]=(uint8_t)(((width>>8)&0xf)<<4|((hBlank>>8)&0xf));
        d[5]=(uint8_t)height;d[6]=(uint8_t)vBlank;d[7]=(uint8_t)(((height>>8)&0xf)<<4|((vBlank>>8)&0xf));
        d[8]=(uint8_t)hFront;d[9]=(uint8_t)hSync;d[10]=(uint8_t)((vFront&0xf)<<4|(vSync&0xf));d[11]=0;
        d[12]=(uint8_t)widthMm;d[13]=(uint8_t)heightMm;d[14]=(uint8_t)(((widthMm>>8)&0xf)<<4|((heightMm>>8)&0xf));
        d[17]=0x1a;                            // digital separate sync, h- v+ (CVT reduced blanking)
        static const uint8_t name[18]={0,0,0,0xfc,0,'U','n','i','X','N','U','\n',' ',' ',' ',' ',' ',' '};
        memcpy(edid+72,name,18);
        for(unsigned at=90;at<126;at+=18)edid[at+3]=0x10;   // dummy descriptors
        edid[126]=1;
        uint8_t *x=edid+128;
        x[0]=0x70;x[1]=0x20;x[2]=19;x[3]=0;x[4]=0;   // DisplayID 2.0 section: 19 bytes of data blocks
        x[5]=0x29;x[6]=0;x[7]=16;containerID(x+8);
        unsigned sum=0;for(unsigned i=1;i<24;++i)sum+=x[i];x[24]=(uint8_t)(0x100-(sum&0xff));
        for(unsigned block=0;block<2;++block) {
            unsigned total=0;for(unsigned i=0;i<127;++i)total+=edid[block*128+i];edid[block*128+127]=(uint8_t)(0x100-(total&0xff));
        }
        // The display's UUID, read by QuartzCore's IOMFB display (IOMobileFramebufferCopyProperty "IOMFBUUID", a string) before it makes
        // one up. WindowServer ties a touch screen to the display whose UUID is the digitizer's "displayUUID" property
        // (WSHIDDisplayEventListener::handle_digitizer_added; macOS run41: "no usable displayUUID property; treating as no digitizer
        // added"), so the framebuffer gives the one the touch device publishes: the container UUID.
        {
            uint8_t u[16];containerID(u);char text[37];
            snprintf(text,sizeof(text),"%02X%02X%02X%02X-%02X%02X-%02X%02X-%02X%02X-%02X%02X%02X%02X%02X%02X",u[0],u[1],u[2],u[3],u[4],u[5],u[6],u[7],
                     u[8],u[9],u[10],u[11],u[12],u[13],u[14],u[15]);
            setProperty("IOMFBUUID",text);
        }
        OSData *data=OSData::withBytes(edid,sizeof(edid));
        if(!data)return;
        setProperty("NativeDisplayEDID",data);   // kept for the worker below, which attaches the display object
        data->release();
        retain();
        thread_t thread=nullptr;
        if(kernel_thread_start(attachDisplayObject,this,&thread)==KERN_SUCCESS)thread_deallocate(thread);
        else release();
    }
    // The IODisplay class is IOGraphicsFamily's, loaded here if nothing has loaded it yet (outside the framebuffer's start).
    static void attachDisplayObject(void *context,wait_result_t) {
        NativeLegacyDisplay *self=static_cast<NativeLegacyDisplay *>(context);
        const OSReturn loaded=OSKextLoadKextWithIdentifier("com.apple.iokit.IOGraphicsFamily");
        OSObject *object=nullptr;
        if(loaded==kOSReturnSuccess || loaded==kOSKextReturnStartStopError) {
            object=OSMetaClass::allocClassWithName("AppleDisplay");
            if(!object)object=OSMetaClass::allocClassWithName("IODisplay");
        }
        IOService *display=OSDynamicCast(IOService,object);
        OSData *edid=OSDynamicCast(OSData,self->getProperty("NativeDisplayEDID"));
        bool attached=false;
        if(display && edid && display->init()) {
            const uint8_t *bytes=static_cast<const uint8_t *>(edid->getBytesNoCopy());
            display->setProperty("IODisplayEDID",edid);
            display->setProperty("DisplayVendorID",(unsigned long long)(bytes[8]<<8|bytes[9]),32);
            display->setProperty("DisplayProductID",(unsigned long long)(bytes[10]|bytes[11]<<8),32);
            display->setName("NativeDisplay");
            attached=display->attach(self);
        }
        IOLog("NativeLegacyDisplay: display object %s (kext %d cls=%s)\n",
              attached?"attached":"not attached",(int)loaded,
              display?display->getMetaClass()->getClassName():"null");
        OSSafeReleaseNULL(object);
        self->release();
        thread_terminate(current_thread());
    }
    // Family slots whose IOMobileFramebufferLegacy code answers kIOReturnUnsupported and that macOS's display clients call to bring
    // the display up, implemented as the virtual-machine display does. The mode is the one color and timing element published
    // above; the active size stays the GOP mode the backend scans out.
    uint32_t colorRemapMode=6;   // what the family's get_color_remap_mode answers before any change
    IOReturn setDigitalOutMode(uint32_t colorID,uint32_t timingID) override {
        const uint32_t n=bumpCall(1);
        unsigned newHz=0;
        if(timingID==kDisplayTiming120)newHz=120u;
        else if(timingID==kDisplayTiming144)newHz=144u;
        else if(timingID==kDisplayTiming60)newHz=60u;
        IOReturn st=(colorID!=kDisplayColorID || !newHz)?kIOReturnBadArgument:kIOReturnSuccess;
        if(n<=16)IOLog("LQ102GPU NLD setDigitalOutMode(color=%u, timing=%u, hz=%u) -> 0x%x\n",colorID,timingID,newHz,(unsigned)st);
        if(st!=kIOReturnSuccess)return st;
        activeRefreshHz=newHz;
        vsyncHz=newHz;
        nanoseconds_to_absolutetime(1000000000ull/newHz,&vsyncInterval);
        (void)native_legacy_set_refresh_properties(this);
        uint32_t width=0,height=0;getDisplayDimensions(&width,&height);
        setProperty("DisplayWidth",width,32);setProperty("DisplayHeight",height,32);setProperty("DPTimingModeId",timingID,32);
        return kIOReturnSuccess;
    }
    IOReturn setDisplayDevice(uint32_t dev) override {
        const uint32_t n=bumpCall(2);
        if(n<=8)IOLog("LQ102GPU NLD setDisplayDevice(%u)\n",dev);
        return kIOReturnSuccess;
    }
    // No gamma hardware: the scanout is the surface as given. The family's get_gamma_table keeps answering unsupported.
    IOReturn setGammaTable(void *) override {
        const uint32_t n=bumpCall(3);
        if(n<=4)IOLog("LQ102GPU NLD setGammaTable #%u\n",n);
        return kIOReturnSuccess;
    }
    IOReturn setColorRemapMode(uint32_t mode) override {
        const uint32_t n=bumpCall(4);
        if(n<=4)IOLog("LQ102GPU NLD setColorRemapMode(%u)\n",mode);
        colorRemapMode=mode;return kIOReturnSuccess;
    }
    IOReturn getColorRemapMode(uint32_t *mode) override {
        const uint32_t n=bumpCall(5);
        if(!mode)return kIOReturnBadArgument;
        *mode=colorRemapMode;
        if(n<=4)IOLog("LQ102GPU NLD getColorRemapMode -> %u\n",*mode);
        return kIOReturnSuccess;
    }
    // No color matrix hardware either; the compositor's matrix is accepted, as the virtual-machine display accepts it.
    IOReturn swapSetColorMatrix(void *,uint32_t a,uint32_t b) override {
        const uint32_t n=bumpCall(6);
        if(n<=4)IOLog("LQ102GPU NLD swapSetColorMatrix(%u,%u)\n",a,b);
        return kIOReturnSuccess;
    }
#endif
#define LEAF(n) __attribute__((noreturn,noinline)) void opaque##n() override { native_legacy_backend_guard(n,this,__builtin_return_address(0)); }
    NATIVE_LEGACY_LEAVES(LEAF)
#undef LEAF
};
OSDefineMetaClassAndStructors(NativeLegacyDisplay,IOMobileFramebufferLegacy)
extern "C" void native_legacy_direct_snapshot(void) {if(gDirectDisplay)gDirectDisplay->snapshot();}
extern "C" unsigned native_legacy_fb_diag(char *out,unsigned cap) {
    if(!out || !cap)return 0;
    if(!gLiveDisplay){out[0]=0;return 0;}
    return gLiveDisplay->fbDiag(out,cap);
}
IOService *native_legacy_display_allocate(void) {return new NativeLegacyDisplay;}
extern "C" void native_legacy_gpu_complete(void *display,int status) {if(display)static_cast<NativeLegacyDisplay *>(display)->gpuComplete(status);}
