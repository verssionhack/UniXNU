// SPDX-License-Identifier: BSD-2-Clause-Patent
// NT36532 standard coordinate firmware on SM8475 QUP0 SE4. The Linux
// nt36523 driver supplies report geometry (10 firmware units per pixel).
#include "LiuqinInputBoard.h"
#include <IOKit/IOBufferMemoryDescriptor.h>
#include <kern/task.h>
extern "C" {
#include "GeniSpi.h"
#include "NvtProtocol.h"
#include "SmmuBypass.h"
extern const uint8_t liuqin_touch_firmware[];
extern const uint64_t liuqin_touch_firmware_size;
extern volatile int32_t native_keyboard_hid_stats[6];
}
namespace {
struct Touch {
    LqRegion gcc, wrapper, se, smmu;
    IOBufferMemoryDescriptor *dma = nullptr;
    LqPin pins[4], irq;
    geni_spi spi = {};
    nvt_bus bus = {};
    nvt_chip chip = {};
    nvt_fw fw = {};
    volatile unsigned pending = 0;
    volatile unsigned irqs = 0;
    unsigned frames=0, errors=0;
    uint16_t lastX=0, lastY=0;
    bool down=false;
};
Touch *touch;
uint32_t rd(void *p, uint32_t r) {return lqRead(reinterpret_cast<uintptr_t>(p),r);}
void wr(void *p, uint32_t r, uint32_t v) {lqWrite(reinterpret_cast<uintptr_t>(p),r,v);}
void us(void *, unsigned n) {lqDelayUs(n);}
void ms(void *, unsigned n) {lqSleep(n);}
void cacheRange(void *address,size_t bytes,int operation) {
    uint64_t ctr;__asm__ volatile("mrs %0, ctr_el0":"=r"(ctr));
    const uintptr_t line=4ULL<<((ctr>>16)&15);
    uintptr_t p=reinterpret_cast<uintptr_t>(address)&~(line-1);
    const uintptr_t end=reinterpret_cast<uintptr_t>(address)+bytes;
    for(;p<end;p+=line) {
        if(operation==0)__asm__ volatile("dc cvac, %0"::"r"(p):"memory");
        else if(operation==1)__asm__ volatile("dc civac, %0"::"r"(p):"memory");
        else __asm__ volatile("dc ivac, %0"::"r"(p):"memory");
    }
    __asm__ volatile("dsb sy":::"memory");
}
void clean(void *,void *p,size_t n) {cacheRange(p,n,0);}
void cleanInvalidate(void *,void *p,size_t n) {cacheRange(p,n,1);}
void invalidate(void *,void *p,size_t n) {cacheRange(p,n,2);}
bool prepareDma() {
    constexpr unsigned bytes=65536;
    touch->dma=IOBufferMemoryDescriptor::inTaskWithPhysicalMask(kernel_task,
        static_cast<IOOptionBits>(kIODirectionInOut)|static_cast<IOOptionBits>(kIOMemoryPhysicallyContiguous),
        2*bytes,0xfffffff000ULL);
    if(!touch->dma || touch->dma->prepare()!=kIOReturnSuccess)return false;
    IOByteCount length=0;
    const addr64_t physical=touch->dma->getPhysicalSegment(0,&length,kIOMemoryMapperNone);
    auto virt=static_cast<uint8_t *>(touch->dma->getBytesNoCopy());
    if(!virt || !physical || length<2*bytes || !touch->smmu.map(0x15000000,0x100000))return false;
    smmu_io io={reinterpret_cast<void *>(touch->smmu.va),rd,wr};
    smmu_plan plan=smmu_plan_bypass(&io,0x5a3,physical,2*bytes);
    const char *error=plan.error?plan.error:smmu_configure_bypass(&io,&plan,0x5a3);
    if(error) {printf("LQ103 TOUCH SMMU fail=%s slot=%u bank=%u\n",error,plan.slot,plan.bank);return false;}
    memset(virt,0,2*bytes);cacheRange(virt,2*bytes,1);
    geni_spi &s=touch->spi;s.use_dma=1;
    s.dma.ctx=nullptr;s.dma.clean=clean;s.dma.clean_inval=cleanInvalidate;s.dma.inval=invalidate;
    s.dma.tx_virt=virt;s.dma.rx_virt=virt+bytes;
    s.dma.tx_phys=physical;s.dma.rx_phys=physical+bytes;s.dma.size=bytes;
    printf("LQ103 TOUCH DMA ready pa=0x%llx sid=0x5a3 slot=%u bank=%u\n",physical,plan.slot,plan.bank);
    return true;
}
int xfer(void *ctx, const uint8_t *tx, uint8_t *rx, size_t n) {
    geni_spi &s=static_cast<Touch *>(ctx)->spi;
    int rc=geni_spi_transfer(&s,tx,rx,n,0);
    if(rc) printf("LQ103 TOUCH xfer err=%d n=%lu if=%x irq=%x status=%x txfs=%x rxfs=%x cfg=%x sel=%x\n",
        rc,n,s.info.if_disable,s.snap_irq,s.snap_status,s.snap_txfs,s.snap_rxfs,
        lqRead(touch->se.va,GENI_SER_M_CLK_CFG),lqRead(touch->se.va,SE_GENI_CLK_SEL));
    return rc;
}
void irq(void *) {
    if (touch && touch->irq.ack()) {
        __atomic_fetch_add(&touch->irqs,1,__ATOMIC_RELAXED);
        __atomic_fetch_add(&touch->pending,1,__ATOMIC_RELEASE);
        thread_wakeup((event_t)&touch->pending);
    }
}
bool setup() {
    touch=new Touch;
    if (!touch || !touch->gcc.map(0x100000,0x63000)) return false;
    const unsigned bits=(1u<<6)|(1u<<7)|(1u<<8)|(1u<<9)|(1u<<14);
    if (!lqVote(touch->gcc.va,bits)) return false;
    const unsigned halts[]={0x27004,0x27008,0x33000,0x3300c,0x274dc};
    for (unsigned off:halts) {
        unsigned tries=0;
        while ((lqRead(touch->gcc.va,off)&(1u<<31)) && !(lqRead(touch->gcc.va,off)&2u)) {
            if (++tries>2000) return false;
            lqDelayUs(10);
        }
    }
    for (unsigned i=0;i<4;++i) if (!touch->pins[i].setup(16+i,1u<<2)) return false;
    if (!touch->irq.setup(21,0) || !touch->wrapper.map(0x9c0000,0x2000) || !touch->se.map(0x990000,0x4000)) return false;
    geni_spi &s=touch->spi;
    s.se={reinterpret_cast<void *>(touch->se.va),rd,wr,us};
    s.wrapper={reinterpret_cast<void *>(touch->wrapper.va),rd,wr,us};
    // Keep status generation enabled, as in the reference GENI DMA path.
    // The engine's SPI remains masked in GIC; the worker polls completion.
    s.poll_only=2; s.poll_limit=200000;
    if(geni_spi_read_info(&s))return false;
    if(s.info.fifo_disabled && !prepareDma())return false;
    int rc=geni_spi_init(&s);
    printf("LQ103 TOUCH SPI info proto=%u if=%x fifo=%u/%u qup=%x\n",s.info.protocol,s.info.if_disable,
        s.info.tx_fifo_depth,s.info.fifo_width_bits,s.info.qup_hw_version);
    if (rc) {printf("LQ103 TOUCH SPI init err=%d proto=%u fifo=%u\n",rc,s.info.protocol,s.info.if_disable);return false;}
    unsigned level=8; uint64_t source=0;
    for (unsigned i=0;i<8;++i) {
        uintptr_t rcg=touch->gcc.va+0x274e4;
        uint64_t hz=lqClockHz(lqRead(rcg,0x1c+i*4),lqRead(rcg,0x5c+i*4),lqRead(rcg,0x9c+i*4));
        if (hz==19200000) {level=i;source=hz;break;}
    }
    if (level==8 || geni_spi_set_clock(&s,9600000,source,level) || geni_spi_setup(&s,0,0)) return false;
    touch->bus={touch,xfer,ms};
    touch->chip.bus=&touch->bus;
    touch->chip.scratch=static_cast<uint8_t *>(IOMallocData(NVT_TRANSFER_LEN+8));
    touch->chip.rxbuf=static_cast<uint8_t *>(IOMallocData(NVT_READ_MAX+2));
    if (!touch->chip.scratch || !touch->chip.rxbuf) return false;
    rc=nvt_identify(&touch->chip);
    printf("LQ103 TOUCH identify err=%d id=%02x%02x%02x%02x%02x%02x\n",rc,
        touch->chip.id[0],touch->chip.id[1],touch->chip.id[2],touch->chip.id[3],touch->chip.id[4],touch->chip.id[5]);
    if (rc || touch->chip.map->event_buf!=0x125800) return false;
    rc=nvt_fw_parse(&touch->fw,liuqin_touch_firmware,liuqin_touch_firmware_size);
    if (!rc) rc=nvt_download_firmware(&touch->chip,&touch->fw);
    if (rc) {printf("LQ103 TOUCH firmware err=%d stage=%u crc=0x%x\n",rc,touch->chip.dl_stage,touch->chip.crc_flags);return false;}
    nvt_fw_info info={};
    rc=nvt_get_fw_info(&touch->chip,&info);
    printf("LQ103 TOUCH firmware ready err=%d extent=%ux%u ver=%u\n",rc,info.abs_x_max,info.abs_y_max,info.fw_ver);
    if (rc || info.defaulted || info.abs_x_max!=18000 || info.abs_y_max!=28800) return false;
    // Use ordinary firmware contact reports; do not enable Sheng's THP matrix mode.
    if (!armcpu_spi_share || armcpu_spi_share(32+208,irq,nullptr)) return false;
    touch->irq.rising();
    return true;
}
void frame() {
    uint8_t data[65]={};
    if (nvt_read(&touch->chip,touch->chip.map->event_buf,data,sizeof(data))) {++touch->errors;return;}
    ++touch->frames;
    bool down=false;
    uint16_t x=touch->lastX,y=touch->lastY;
    for (unsigned i=0;i<10;++i) {
        const uint8_t *p=data+6*i;
        const unsigned id=p[0]>>3,state=p[0]&7;
        if (!id || id>10 || (state!=1 && state!=2)) continue;
        unsigned px=(unsigned(p[1])<<8)|p[2],py=(unsigned(p[3])<<8)|p[4];
        if (px>=18000 || py>=28800) continue;
        // Invert NativeLegacyDisplay's landscape-to-panel copy:
        // physical row = logical X, physical column = 1799 - logical Y.
        x=py/10; y=1799-px/10; down=true; break;
    }
    if (down || touch->down) {
        uint8_t report[]={0x1b,uint8_t(down),uint8_t(x),uint8_t(x>>8),uint8_t(y),uint8_t(y>>8)};
        sheng_keyboard_cover_input(liuqin_touch_hid(),report,sizeof(report));
    }
    touch->down=down;touch->lastX=x;touch->lastY=y;
}
void worker(void *,wait_result_t) {
    if (!setup()) {printf("LQ103 TOUCH setup failed\n");thread_terminate(current_thread());return;}
    printf("LQ103 TOUCH ready spi=0x990000 irq=21\n");
    unsigned ticks=0;
    for (;;) {
        uint64_t deadline;clock_interval_to_deadline(100,NSEC_PER_MSEC,&deadline);
        assert_wait_deadline((event_t)&touch->pending,THREAD_UNINT,deadline);
        if (!__atomic_load_n(&touch->pending,__ATOMIC_ACQUIRE)) thread_block(THREAD_CONTINUE_NULL);
        else clear_wait(current_thread(),THREAD_AWAKENED);
        if (__atomic_exchange_n(&touch->pending,0,__ATOMIC_ACQ_REL)) frame();
        if(++ticks%50==0)printf("LQ103 TOUCH STAT irq=%u frames=%u errors=%u pin=%u cfg=%x hid=%d/%d/%d last=%x xy=%u/%u down=%u\n",
            touch->irqs,touch->frames,touch->errors,touch->irq.level(),lqRead(touch->irq.va,8),
            native_keyboard_hid_stats[0],native_keyboard_hid_stats[1],native_keyboard_hid_stats[2],
            native_keyboard_hid_stats[5],touch->lastX,touch->lastY,touch->down);
    }
}
}
extern "C" void liuqin_touch_start(void) {
    thread_t thread;
    if (kernel_thread_start(worker,nullptr,&thread)==KERN_SUCCESS) thread_deallocate(thread);
}
