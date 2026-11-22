/* SPDX-License-Identifier: BSD-2-Clause-Patent */
/* SM8475 (liuqin, Adreno 730.1) GPU power, clock, and SMMU board constants & gated bring-up sequence.
 * Sources:
 *   - linux-release-clean/drivers/clk/qcom/gcc-sm8450.c (GCC GPU page 0x00181000, vote page 0x00162000)
 *   - linux-release-clean/drivers/clk/qcom/gpucc-sm8450.c (SM8475 LUCID_OLE PLL0/PLL1, RCGs, CX GDSC, branches)
 *   - Live post-ABL FDT on be7ca114 (r102-p12): gpucc@3d90000/0xa000, adreno_smmu@3da0000/0x40000, gpu@3d00000/0x40000.
 */
#ifndef LIUQIN_GPU_POWER_BOARD_H
#define LIUQIN_GPU_POWER_BOARD_H
#include <stdint.h>

#define GPB_GCC_BASE       0x00100000ULL
#define GPB_GCC_SIZE       0x1000ULL
#define GPB_GCC_GPU_PAGE   0x00181000ULL   /* gcc-sm8450.c: 0x81000 page */
#define GPB_GCC_VOTE_PAGE  0x00162000ULL   /* gcc-sm8450.c: 0x62000 vote page */
#define GPB_GPUCC_BASE     0x03d90000ULL
#define GPB_GPUCC_SIZE     0xa000ULL
#define GPB_SMMU_BASE      0x03da0000ULL
#define GPB_SMMU_GR0_SIZE  0x1000ULL
#define GPB_GPU_BASE       0x03d00000ULL
#define GPB_GPU_WINDOW     0x1000ULL

/* GCC GPU page (0x00181000) & vote page (0x00162000) offsets — gcc-sm8450.c */
#define GPB_GCC_GPU_CFG_AHB       0x004u   /* 0x81004 */
#define GPB_GCC_GPU_MEMNOC_GFX    0x010u   /* 0x81010 */
#define GPB_GCC_GPU_SNOC_DVM_GFX  0x018u   /* 0x81018 */
#define GPB_GCC_DDRSS_GPU_AXI     0x154u   /* 0x81154 */
#define GPB_GCC_PLL_VOTE          0x000u   /* 0x62000: bit 15 GPLL0, bit 16 GPLL0_DIV */
#define GPB_GPLL0_VOTES           ((1u << 15) | (1u << 16))
#define GPB_CBCR_CLK_OFF          (1u << 31)
#define GPB_CBCR_ENABLE           (1u << 0)

/* GPUCC (0x03d90000) offsets — gpucc-sm8450.c (qcom,sm8475-gpucc) */
#define GPB_CC_PLL0               0x0000u
#define GPB_CC_PLL1               0x1000u
#define GPB_CC_SMMU_VOTE_CLK      0x7000u  /* gpu_cc_hlos1_vote_gpu_smmu_clk */
#define GPB_CC_CXO_AON_CLK        0x9004u
#define GPB_CC_DEMET_CLK          0x900cu
#define GPB_CC_GX_GDSCR           0x905cu
#define GPB_CC_CX_GDSCR           0x9108u
#define GPB_CC_AHB_CLK            0x911cu
#define GPB_CC_CX_GMU_CLK         0x913cu
#define GPB_CC_CXO_CLK            0x9144u
#define GPB_CC_HUB_CX_INT_CLK     0x9148u
#define GPB_CC_GMU_RCGR           0x9318u
#define GPB_CC_HUB_RCGR           0x93ecu
#define GPB_CC_CX_GDS_HW_CTRL     0x953cu

#define GPB_GDSC_RETAIN_MEM       (1u << 14)
#define GPB_GDSC_RETAIN_PERIPH    (1u << 13)
#define GPB_GDSC_RETAIN_FF        (1u << 11)
#define GPB_GDSC_POLL_US          2000u
#define GPB_GDSC_PWR_ON           (1u << 31)
#define GPB_GDSC_SW_COLLAPSE      (1u << 0)

/* CLK_ALPHA_PLL_TYPE_LUCID_OLE offsets (SM8475 gpucc-sm8450.c:780-788) */
#define GPB_PLL_MODE              0x00u
#define GPB_PLL_OPMODE            0x04u
#define GPB_PLL_L_VAL             0x10u
#define GPB_PLL_USER_CTL          0x18u
#define GPB_PLL_LOCK_DET          (1u << 31)
#define GPB_PLL_OUTCTRL           (1u << 0)
#define GPB_PLL_RESET_N           (1u << 2)
#define GPB_PLL_OUT_MASK          0x7u
#define GPB_PLL_RUN               1u

/* RCG2 bits */
#define GPB_RCG_UPDATE            (1u << 0)
#define GPB_RCG_ROOT_EN           (1u << 1)
#define GPB_RCG_ROOT_OFF          (1u << 31)
#define GPB_RCG_CFG_CLEAR         (0x1fu | (7u << 8) | (3u << 12) | (1u << 20))

/* ARM SMMUv2 GR0 */
#define GPB_SMMU_SCR0             0x00u
#define GPB_SMMU_ID0              0x20u
#define GPB_SMMU_ID1              0x24u
#define GPB_SMMU_ID2              0x28u
#define GPB_SMMU_GFSR             0x48u
#define GPB_SMMU_SMR(n)           (0x800u + 4u * (n))
#define GPB_SMMU_S2CR(n)          (0xc00u + 4u * (n))
#define GPB_SMMU_MAX_SMR          128u

#define GPB_RBBM_STATUS_BYTES     (0x0210u * 4u)

enum gpb_state { GPB_NOT_RUN = 0, GPB_DONE = 1, GPB_SKIPPED_PREREQ = 2, GPB_SKIPPED_MODE = 3, GPB_NOMAP = 4 };
enum { GPB_WIN_GCC_GPU = 0, GPB_WIN_GCC_VOTE = 1, GPB_WIN_GPUCC = 2, GPB_WIN_SMMU = 3, GPB_WIN_GPU = 4 };

struct gpb_io {
    void *cookie;
    int (*read32)(void *cookie, unsigned window, uint32_t offset, uint32_t *out);
    int (*write32)(void *cookie, unsigned window, uint32_t offset, uint32_t value);
    void (*delay_us)(void *cookie, unsigned us);
};

struct gpb_result {
    unsigned mode;
    enum gpb_state gcc, cc, smmu, gpu;
    uint32_t cfg_ahb, cfg_ahb_after, memnoc, dvm, pll_vote;
    uint32_t cx_gdscr, gx_gdscr, cc_ahb, cc_smmu, cc_gmu;
    uint32_t scr0, id0, id1, id2, gfsr;
    uint32_t smr_valid, smr_first, smr_first_val, s2cr_first_val;
    uint32_t rbbm_status;
    uint32_t cx_before, cx_hwctrl, cc_smmu_before;
    unsigned powered_cx, powered_clocks, enabled_ahb;
    int io_error;
};

struct gpb_gmu_clocks {
    uint32_t pll1_mode, pll1_opmode, pll1_l, pll1_user;
    uint32_t gmu_cmd, gmu_cfg, hub_cmd, hub_cfg;
    uint32_t cx_gmu, cxo, hub_cx_int, demet, axi, memnoc, gpll0_vote;
    int done;
};

struct gpb_gmu_clock_on {
    unsigned step;
    int failed;
    unsigned lock_polls, hub_polls, gmu_polls;
    uint32_t pll1_mode, pll1_opmode, hub_cfg, gmu_cfg, cx_gmu;
};

static inline int gpb_clock_on(uint32_t cbcr) { return (cbcr & GPB_CBCR_CLK_OFF) == 0; }
static inline int gpb_cfg_ahb_enabled(uint32_t cbcr) { return (cbcr & GPB_CBCR_ENABLE) != 0; }
static inline int gpb_gdsc_on(uint32_t gdscr) { return (gdscr & GPB_GDSC_PWR_ON) != 0; }
static inline unsigned gpb_smmu_num_smr(uint32_t id0) { return id0 & 0xffu; }
static inline unsigned gpb_smmu_num_cb(uint32_t id1) { return id1 & 0xffu; }

static inline int gpb_rd(const struct gpb_io *io, struct gpb_result *r, unsigned window, uint32_t offset, uint32_t *out) {
    uint32_t v = 0;
    if (io->read32(io->cookie, window, offset, &v)) { r->io_error = 1; *out = 0; return -1; }
    *out = v;
    return 0;
}

static inline void gpb_run(const struct gpb_io *io, unsigned mode, unsigned have, struct gpb_result *r) {
    __builtin_memset(r, 0, sizeof *r);
    r->mode = mode;
    if (!mode || !(have & (1u << GPB_WIN_GCC_GPU))) { r->gcc = (mode ? GPB_NOMAP : GPB_SKIPPED_MODE); return; }
    if (gpb_rd(io, r, GPB_WIN_GCC_GPU, GPB_GCC_GPU_CFG_AHB, &r->cfg_ahb)) return;
    gpb_rd(io, r, GPB_WIN_GCC_GPU, GPB_GCC_GPU_MEMNOC_GFX, &r->memnoc);
    gpb_rd(io, r, GPB_WIN_GCC_GPU, GPB_GCC_GPU_SNOC_DVM_GFX, &r->dvm);
    if (have & (1u << GPB_WIN_GCC_VOTE)) gpb_rd(io, r, GPB_WIN_GCC_VOTE, GPB_GCC_PLL_VOTE, &r->pll_vote);
    r->cfg_ahb_after = r->cfg_ahb;
    if (!gpb_cfg_ahb_enabled(r->cfg_ahb) && mode >= 2) {
        if (!io->write32(io->cookie, GPB_WIN_GCC_GPU, GPB_GCC_GPU_CFG_AHB, r->cfg_ahb | GPB_CBCR_ENABLE)) {
            r->enabled_ahb = 1;
            gpb_rd(io, r, GPB_WIN_GCC_GPU, GPB_GCC_GPU_CFG_AHB, &r->cfg_ahb_after);
        } else r->io_error = 1;
    }
    r->gcc = GPB_DONE;
    if (!(have & (1u << GPB_WIN_GPUCC))) r->cc = GPB_NOMAP;
    else if (!gpb_cfg_ahb_enabled(r->cfg_ahb_after)) r->cc = GPB_SKIPPED_PREREQ;
    else {
        gpb_rd(io, r, GPB_WIN_GPUCC, GPB_CC_CX_GDSCR, &r->cx_gdscr);
        gpb_rd(io, r, GPB_WIN_GPUCC, GPB_CC_GX_GDSCR, &r->gx_gdscr);
        gpb_rd(io, r, GPB_WIN_GPUCC, GPB_CC_AHB_CLK, &r->cc_ahb);
        gpb_rd(io, r, GPB_WIN_GPUCC, GPB_CC_SMMU_VOTE_CLK, &r->cc_smmu);
        gpb_rd(io, r, GPB_WIN_GPUCC, GPB_CC_CX_GMU_CLK, &r->cc_gmu);
        r->cc = GPB_DONE;
    }
    r->cx_before = r->cx_gdscr;
    r->cc_smmu_before = r->cc_smmu;
    if (mode >= 3 && r->cc == GPB_DONE) {
        if (!gpb_gdsc_on(r->cx_gdscr)) {
            uint32_t v = r->cx_gdscr, st = 0;
            int bad = io->write32(io->cookie, GPB_WIN_GPUCC, GPB_CC_CX_GDSCR, v & ~GPB_GDSC_SW_COLLAPSE);
            if (!bad) {
                unsigned waited = 0;
                if (io->delay_us) io->delay_us(io->cookie, 1);
                for (;;) {
                    if (gpb_rd(io, r, GPB_WIN_GPUCC, GPB_CC_CX_GDS_HW_CTRL, &st)) { bad = 1; break; }
                    if (gpb_gdsc_on(st) || waited >= GPB_GDSC_POLL_US) break;
                    if (io->delay_us) io->delay_us(io->cookie, 10);
                    waited += 10;
                }
                r->cx_hwctrl = st;
                if (!bad && gpb_gdsc_on(st)) {
                    gpb_rd(io, r, GPB_WIN_GPUCC, GPB_CC_CX_GDSCR, &v);
                    bad |= io->write32(io->cookie, GPB_WIN_GPUCC, GPB_CC_CX_GDSCR, v | GPB_GDSC_RETAIN_MEM | GPB_GDSC_RETAIN_PERIPH);
                    if (io->delay_us) io->delay_us(io->cookie, 1);
                    bad |= io->write32(io->cookie, GPB_WIN_GPUCC, GPB_CC_CX_GDSCR, v | GPB_GDSC_RETAIN_MEM | GPB_GDSC_RETAIN_PERIPH | GPB_GDSC_RETAIN_FF);
                    if (io->delay_us) io->delay_us(io->cookie, 1);
                    gpb_rd(io, r, GPB_WIN_GPUCC, GPB_CC_CX_GDSCR, &r->cx_gdscr);
                    r->powered_cx = !bad && gpb_gdsc_on(r->cx_hwctrl);
                }
            }
            if (bad) r->io_error = 1;
        } else {
            r->powered_cx = 1;
        }
        if (r->powered_cx) {
            uint32_t a = 0, c = 0;
            gpb_rd(io, r, GPB_WIN_GPUCC, GPB_CC_AHB_CLK, &a);
            gpb_rd(io, r, GPB_WIN_GPUCC, GPB_CC_SMMU_VOTE_CLK, &c);
            int cbad = io->write32(io->cookie, GPB_WIN_GPUCC, GPB_CC_AHB_CLK, a | GPB_CBCR_ENABLE);
            cbad |= io->write32(io->cookie, GPB_WIN_GPUCC, GPB_CC_SMMU_VOTE_CLK, c | GPB_CBCR_ENABLE);
            unsigned waited = 0;
            for (;;) {
                if (gpb_rd(io, r, GPB_WIN_GPUCC, GPB_CC_SMMU_VOTE_CLK, &r->cc_smmu)) { cbad = 1; break; }
                if (gpb_clock_on(r->cc_smmu) || waited >= 500) break;
                if (io->delay_us) io->delay_us(io->cookie, 10);
                waited += 10;
            }
            gpb_rd(io, r, GPB_WIN_GPUCC, GPB_CC_AHB_CLK, &r->cc_ahb);
            r->powered_clocks = !cbad && gpb_clock_on(r->cc_smmu);
            if (cbad) r->io_error = 1;
        }
    }
    if (!(have & (1u << GPB_WIN_SMMU))) r->smmu = GPB_NOMAP;
    else if (r->cc != GPB_DONE || !gpb_gdsc_on(r->cx_gdscr) || !gpb_clock_on(r->cc_smmu)) r->smmu = GPB_SKIPPED_PREREQ;
    else {
        gpb_rd(io, r, GPB_WIN_SMMU, GPB_SMMU_SCR0, &r->scr0);
        gpb_rd(io, r, GPB_WIN_SMMU, GPB_SMMU_ID0, &r->id0);
        gpb_rd(io, r, GPB_WIN_SMMU, GPB_SMMU_ID1, &r->id1);
        gpb_rd(io, r, GPB_WIN_SMMU, GPB_SMMU_ID2, &r->id2);
        gpb_rd(io, r, GPB_WIN_SMMU, GPB_SMMU_GFSR, &r->gfsr);
        unsigned n = gpb_smmu_num_smr(r->id0);
        if (n > GPB_SMMU_MAX_SMR) n = GPB_SMMU_MAX_SMR;
        r->smr_first = 0xffffffffu;
        for (unsigned i = 0; i < n; ++i) {
            uint32_t smr = 0;
            if (gpb_rd(io, r, GPB_WIN_SMMU, GPB_SMMU_SMR(i), &smr)) break;
            if (smr & (1u << 31)) {
                ++r->smr_valid;
                if (r->smr_first == 0xffffffffu) {
                    r->smr_first = i;
                    r->smr_first_val = smr;
                    gpb_rd(io, r, GPB_WIN_SMMU, GPB_SMMU_S2CR(i), &r->s2cr_first_val);
                }
            }
        }
        r->smmu = GPB_DONE;
    }
    if (!(have & (1u << GPB_WIN_GPU))) r->gpu = GPB_NOMAP;
    else if (r->cc != GPB_DONE || !gpb_gdsc_on(r->cx_gdscr) || !gpb_gdsc_on(r->gx_gdscr)) r->gpu = GPB_SKIPPED_PREREQ;
    else {
        gpb_rd(io, r, GPB_WIN_GPU, GPB_RBBM_STATUS_BYTES, &r->rbbm_status);
        r->gpu = GPB_DONE;
    }
}

static inline int gpb_gmu_regs_readable(const struct gpb_result *r, const struct gpb_gmu_clocks *k) {
    return k->done && gpb_gdsc_on(r->cx_gdscr) && gpb_clock_on(r->cc_ahb) && gpb_clock_on(k->cx_gmu);
}

static inline void gpb_read_gmu_clocks(const struct gpb_io *io, struct gpb_result *r, struct gpb_gmu_clocks *k) {
    __builtin_memset(k, 0, sizeof *k);
    if (r->cc != GPB_DONE || !gpb_cfg_ahb_enabled(r->cfg_ahb_after)) return;
    gpb_rd(io, r, GPB_WIN_GPUCC, GPB_CC_PLL1 + GPB_PLL_MODE, &k->pll1_mode);
    gpb_rd(io, r, GPB_WIN_GPUCC, GPB_CC_PLL1 + GPB_PLL_OPMODE, &k->pll1_opmode);
    gpb_rd(io, r, GPB_WIN_GPUCC, GPB_CC_PLL1 + GPB_PLL_L_VAL, &k->pll1_l);
    gpb_rd(io, r, GPB_WIN_GPUCC, GPB_CC_PLL1 + GPB_PLL_USER_CTL, &k->pll1_user);
    gpb_rd(io, r, GPB_WIN_GPUCC, GPB_CC_GMU_RCGR, &k->gmu_cmd);
    gpb_rd(io, r, GPB_WIN_GPUCC, GPB_CC_GMU_RCGR + 4, &k->gmu_cfg);
    gpb_rd(io, r, GPB_WIN_GPUCC, GPB_CC_HUB_RCGR, &k->hub_cmd);
    gpb_rd(io, r, GPB_WIN_GPUCC, GPB_CC_HUB_RCGR + 4, &k->hub_cfg);
    gpb_rd(io, r, GPB_WIN_GPUCC, GPB_CC_CX_GMU_CLK, &k->cx_gmu);
    gpb_rd(io, r, GPB_WIN_GPUCC, GPB_CC_CXO_CLK, &k->cxo);
    gpb_rd(io, r, GPB_WIN_GPUCC, GPB_CC_HUB_CX_INT_CLK, &k->hub_cx_int);
    gpb_rd(io, r, GPB_WIN_GPUCC, GPB_CC_DEMET_CLK, &k->demet);
    gpb_rd(io, r, GPB_WIN_GCC_GPU, GPB_GCC_DDRSS_GPU_AXI, &k->axi);
    k->memnoc = r->memnoc;
    if (gpb_rd(io, r, GPB_WIN_GCC_VOTE, GPB_GCC_PLL_VOTE, &k->gpll0_vote)) k->gpll0_vote = r->pll_vote;
    k->done = 1;
}

/* SM8475 LUCID_OLE PLL config (gpucc-sm8450.c:53-65, 94-106):
 *   PLL0: L=0x1d, alpha=0xb000
 *   PLL1: L=0x34, alpha=0x1555 (1000 MHz -> /2 = 500 MHz GMU OPP)
 */
static inline int gpb_pll_configure(const struct gpb_io *io, struct gpb_result *r, uint32_t base, uint32_t l, uint32_t alpha) {
    static const uint32_t off[] = {0x10, 0x14, 0x20, 0x24, 0x28, 0x18, 0x1c, 0x2c, 0x30, 0x34, 0x38};
    const uint32_t val[] = {l | (0x44u << 16) | (0x44u << 24), alpha, 0x20485699u, 0x00182261u, 0x82aa299cu, 0, 5, 0, 3, 0x9000, 0x34};
    uint32_t mode = 0;
    for (unsigned i = 0; i < sizeof off / sizeof off[0]; ++i)
        if (val[i] && io->write32(io->cookie, GPB_WIN_GPUCC, base + off[i], val[i])) return -1;
    if (gpb_rd(io, r, GPB_WIN_GPUCC, base + GPB_PLL_MODE, &mode)) return -1;
    if (io->write32(io->cookie, GPB_WIN_GPUCC, base + GPB_PLL_MODE, mode & ~GPB_PLL_OUTCTRL)) return -1;
    if (io->write32(io->cookie, GPB_WIN_GPUCC, base + GPB_PLL_OPMODE, 0)) return -1;
    if (gpb_rd(io, r, GPB_WIN_GPUCC, base + GPB_PLL_MODE, &mode)) return -1;
    return io->write32(io->cookie, GPB_WIN_GPUCC, base + GPB_PLL_MODE, mode | GPB_PLL_RESET_N);
}

static inline int gpb_pll_running(uint32_t mode, uint32_t opmode) { return (opmode & GPB_PLL_RUN) && (mode & GPB_PLL_OUTCTRL); }

static inline int gpb_rcg_set(const struct gpb_io *io, struct gpb_result *r, uint32_t rcgr, uint32_t sel, uint32_t div,
                              uint32_t *cfg_after, unsigned *polls) {
    uint32_t cmd = 0, cfg = 0;
    int timeout = 1;
    if (gpb_rd(io, r, GPB_WIN_GPUCC, rcgr, &cmd) || io->write32(io->cookie, GPB_WIN_GPUCC, rcgr, cmd | GPB_RCG_ROOT_EN)) return -1;
    for (unsigned i = 0; i < 500; ++i) {
        if (gpb_rd(io, r, GPB_WIN_GPUCC, rcgr, &cmd)) return -1;
        if (!(cmd & GPB_RCG_ROOT_OFF)) { timeout = 0; break; }
        if (io->delay_us) io->delay_us(io->cookie, 1);
    }
    if (timeout) return 1;
    if (gpb_rd(io, r, GPB_WIN_GPUCC, rcgr + 4, &cfg) ||
        io->write32(io->cookie, GPB_WIN_GPUCC, rcgr + 4, (cfg & ~GPB_RCG_CFG_CLEAR) | (sel << 8) | div)) return -1;
    if (gpb_rd(io, r, GPB_WIN_GPUCC, rcgr, &cmd) || io->write32(io->cookie, GPB_WIN_GPUCC, rcgr, cmd | GPB_RCG_UPDATE)) return -1;
    timeout = 1;
    for (unsigned i = 0; i < 500; ++i) {
        ++*polls;
        if (gpb_rd(io, r, GPB_WIN_GPUCC, rcgr, &cmd)) return -1;
        if (!(cmd & GPB_RCG_UPDATE)) { timeout = 0; break; }
        if (io->delay_us) io->delay_us(io->cookie, 1);
    }
    if (timeout) return 1;
    if (io->write32(io->cookie, GPB_WIN_GPUCC, rcgr, cmd & ~GPB_RCG_ROOT_EN)) return -1;
    return gpb_rd(io, r, GPB_WIN_GPUCC, rcgr + 4, cfg_after) ? -1 : 0;
}

static inline int gpb_set_bit0(const struct gpb_io *io, struct gpb_result *r, unsigned w, uint32_t off) {
    uint32_t v = 0;
    if (gpb_rd(io, r, w, off, &v)) return -1;
    return (v & GPB_CBCR_ENABLE) ? 0 : io->write32(io->cookie, w, off, v | GPB_CBCR_ENABLE);
}

static inline void gpb_gmu_clocks_on(const struct gpb_io *io, struct gpb_result *r, const struct gpb_gmu_clocks *k,
                                     struct gpb_gmu_clock_on *o) {
    __builtin_memset(o, 0, sizeof *o);
    int e = 0;
    uint32_t v = 0;
    o->step = 1;
    if (!k->done || !gpb_gdsc_on(r->cx_gdscr)) { o->failed = 1; return; }
    if (gpb_rd(io, r, GPB_WIN_GCC_VOTE, GPB_GCC_PLL_VOTE, &v)) goto io;
    if ((v & GPB_GPLL0_VOTES) != GPB_GPLL0_VOTES) {
        if (io->write32(io->cookie, GPB_WIN_GCC_VOTE, GPB_GCC_PLL_VOTE, v | GPB_GPLL0_VOTES)) goto io;
        if (io->delay_us) io->delay_us(io->cookie, 10);
    }
    o->step = 2;
    if (!gpb_pll_running(k->pll1_mode, k->pll1_opmode)) {
        uint32_t m0 = 0, op0 = 0;
        if (gpb_rd(io, r, GPB_WIN_GPUCC, GPB_CC_PLL0 + GPB_PLL_MODE, &m0) ||
            gpb_rd(io, r, GPB_WIN_GPUCC, GPB_CC_PLL0 + GPB_PLL_OPMODE, &op0)) goto io;
        if (!gpb_pll_running(m0, op0) && gpb_pll_configure(io, r, GPB_CC_PLL0, 0x1du, 0xb000u)) goto io;
        if (gpb_pll_configure(io, r, GPB_CC_PLL1, 0x34u, 0x1555u)) goto io;
        o->step = 3;
        if (gpb_rd(io, r, GPB_WIN_GPUCC, GPB_CC_PLL1 + GPB_PLL_MODE, &v) ||
            io->write32(io->cookie, GPB_WIN_GPUCC, GPB_CC_PLL1 + GPB_PLL_MODE, v | GPB_PLL_RESET_N) ||
            io->write32(io->cookie, GPB_WIN_GPUCC, GPB_CC_PLL1 + GPB_PLL_OPMODE, GPB_PLL_RUN)) goto io;
        e = 1;
        for (unsigned i = 0; i < 1500; ++i) {
            ++o->lock_polls;
            if (gpb_rd(io, r, GPB_WIN_GPUCC, GPB_CC_PLL1 + GPB_PLL_MODE, &v)) goto io;
            if (v & GPB_PLL_LOCK_DET) { e = 0; break; }
            if (io->delay_us) io->delay_us(io->cookie, 1);
        }
        if (e) { o->failed = 1; goto out; }
        if (gpb_rd(io, r, GPB_WIN_GPUCC, GPB_CC_PLL1 + GPB_PLL_USER_CTL, &v) ||
            io->write32(io->cookie, GPB_WIN_GPUCC, GPB_CC_PLL1 + GPB_PLL_USER_CTL, v | GPB_PLL_OUT_MASK) ||
            gpb_rd(io, r, GPB_WIN_GPUCC, GPB_CC_PLL1 + GPB_PLL_MODE, &v) ||
            io->write32(io->cookie, GPB_WIN_GPUCC, GPB_CC_PLL1 + GPB_PLL_MODE, v | GPB_PLL_OUTCTRL)) goto io;
    }
    o->step = 4;
    /* SM8475 gpu_cc_hub_clk_src: 150 MHz = GPLL0_DIV (sel 6) / 2 (hid_div = 3), per a6xx_gmu.c:1080 & gpucc-sm8450.c:220 */
    e = gpb_rcg_set(io, r, GPB_CC_HUB_RCGR, 6u, 3u, &o->hub_cfg, &o->hub_polls);
    if (e) { o->failed = e < 0 ? 2 : 1; goto out; }
    o->step = 5;
    /* SM8475 gpu_cc_gmu_clk_src: 200 MHz = GPLL0_DIV (sel 6) / 1.5 (hid_div = 2) */
    e = gpb_rcg_set(io, r, GPB_CC_GMU_RCGR, 6u, 2u, &o->gmu_cfg, &o->gmu_polls);
    if (e) { o->failed = e < 0 ? 2 : 1; goto out; }
    o->step = 6;
    if (gpb_set_bit0(io, r, GPB_WIN_GPUCC, GPB_CC_CXO_AON_CLK) ||
        gpb_set_bit0(io, r, GPB_WIN_GPUCC, GPB_CC_DEMET_CLK) ||
        gpb_set_bit0(io, r, GPB_WIN_GPUCC, GPB_CC_AHB_CLK) ||
        gpb_set_bit0(io, r, GPB_WIN_GPUCC, GPB_CC_CX_GMU_CLK) ||
        gpb_set_bit0(io, r, GPB_WIN_GPUCC, GPB_CC_CXO_CLK) ||
        gpb_set_bit0(io, r, GPB_WIN_GCC_GPU, GPB_GCC_DDRSS_GPU_AXI) ||
        gpb_set_bit0(io, r, GPB_WIN_GCC_GPU, GPB_GCC_GPU_MEMNOC_GFX) ||
        gpb_set_bit0(io, r, GPB_WIN_GPUCC, GPB_CC_HUB_CX_INT_CLK)) goto io;
    e = 1;
    for (unsigned i = 0; i < 500; ++i) {
        if (gpb_rd(io, r, GPB_WIN_GPUCC, GPB_CC_CX_GMU_CLK, &o->cx_gmu)) goto io;
        if (gpb_clock_on(o->cx_gmu)) { e = 0; break; }
        if (io->delay_us) io->delay_us(io->cookie, 1);
    }
    if (e) { o->failed = 1; goto out; }
    o->step = 7;
    goto out;
io:
    o->failed = 2;
out:
    gpb_rd(io, r, GPB_WIN_GPUCC, GPB_CC_PLL1 + GPB_PLL_MODE, &o->pll1_mode);
    gpb_rd(io, r, GPB_WIN_GPUCC, GPB_CC_PLL1 + GPB_PLL_OPMODE, &o->pll1_opmode);
}

#endif
