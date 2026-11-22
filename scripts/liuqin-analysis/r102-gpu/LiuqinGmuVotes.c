/* SPDX-License-Identifier: BSD-2-Clause-Patent */
/* SM8475 / Adreno 730.1 GMU HFI vote & static BW table builder.
 * Combines live hardware cmd-db ARC/BCM reads with the A730 12-level static BW table
 * (a6xx_hfi.c:a730_build_bw_table) and live FDT 12 active GPU OPPs + 2 GMU OPPs.
 */
#include "ShengGmuVotes.h"
#include "AdrenoHfiVotes.h"
#include "AdrenoHfiStartup.h"

#define LIUQIN_CHIP_ID 0x07030001u
#define LIUQIN_GPU_OPPS 13u
#define LIUQIN_GMU_OPPS 3u
#define LIUQIN_BW_LEVELS 12u

static const uint64_t kGpuHz[LIUQIN_GPU_OPPS] = {
    0ULL, 220000000ULL, 285000000ULL, 317000000ULL, 350000000ULL, 421000000ULL,
    492000000ULL, 545000000ULL, 599000000ULL, 640000000ULL, 734000000ULL, 791000000ULL, 818000000ULL
};
static const uint32_t kGpuLevels[LIUQIN_GPU_OPPS] = {
    0u, 56u, 56u, 64u, 64u, 80u, 128u, 144u, 192u, 224u, 256u, 320u, 384u
};
/* Map each GPU OPP (1..12) to an A730 static BW level (1..11) */
static const uint32_t kGpuOppToBw[LIUQIN_GPU_OPPS] = {
    0u, 1u, 2u, 3u, 4u, 5u, 6u, 7u, 8u, 9u, 10u, 11u, 11u
};
static const uint64_t kGmuHz[LIUQIN_GMU_OPPS] = {
    0ULL, 200000000ULL, 500000000ULL
};
static const uint32_t kGmuLevels[LIUQIN_GMU_OPPS] = {
    0u, 64u, 128u
};
/* Exact a730_build_bw_table DDR votes (SH0, MC0, ACV) verified via AdrenoHfiStartupValidate */
static const uint32_t kA730DdrData[LIUQIN_BW_LEVELS][3] = {
    { 0x40000000u, 0x40000000u, 0x40000000u },
    { 0x600002e8u, 0x600003d0u, 0x60000008u },
    { 0x6000068du, 0x6000089au, 0x60000008u },
    { 0x600007f2u, 0x60000a6eu, 0x60000008u },
    { 0x600009e5u, 0x60000cfdu, 0x60000008u },
    { 0x60000b29u, 0x60000ea6u, 0x60000008u },
    { 0x60001698u, 0x60001da8u, 0x60000008u },
    { 0x600018d2u, 0x60002093u, 0x60000008u },
    { 0x60001e66u, 0x600027e6u, 0x60000008u },
    { 0x600027c2u, 0x6000342fu, 0x60000008u },
    { 0x60002e71u, 0x60003cf5u, 0x60000008u },
    { 0x600030aeu, 0x60003fe5u, 0x60000008u },
};

AdrenoHfiStartupStatus ShengGmuBuildStartup(const ShengGmuVoteInputs *in, AdrenoHfiStartupConfig *out)
{
    if (!in || !out || in->chip_id != LIUQIN_CHIP_ID || in->gmxc_present > 1 ||
        in->enable_acd > 1 || in->enable_ifpc > 1 ||
        (!in->gmxc_present && (in->gmxc.data || in->gmxc.bytes)))
        return AdrenoHfiStartupInvalid;

    AdrenoHfiStartupConfig c = {0};
    uint32_t votes[16];
    const ShengGmuAux *gpu_secondary = in->gmxc_present ? &in->gmxc : &in->mx;

    if (AdrenoHfiArcVotes(kGpuLevels, LIUQIN_GPU_OPPS, in->gfx.data, in->gfx.bytes,
                          gpu_secondary->data, gpu_secondary->bytes, votes, 16))
        return AdrenoHfiStartupInvalid;
    c.gpu_count = LIUQIN_GPU_OPPS;
    for (unsigned i = 0; i < LIUQIN_GPU_OPPS; ++i) {
        c.gpu[i] = (AdrenoHfiPerformanceLevel){ kGpuHz[i], votes[i] };
    }

    if (AdrenoHfiArcVotes(kGmuLevels, LIUQIN_GMU_OPPS, in->cx.data, in->cx.bytes,
                          in->mx.data, in->mx.bytes, votes, 16))
        return AdrenoHfiStartupInvalid;
    c.gmu_count = LIUQIN_GMU_OPPS;
    for (unsigned i = 0; i < LIUQIN_GMU_OPPS; ++i) {
        c.gmu[i] = (AdrenoHfiPerformanceLevel){ kGmuHz[i], votes[i] };
    }

    if (!in->sh0.address || !in->mc0.address || !in->acv.address || !in->cn0_address)
        return AdrenoHfiStartupInvalid;

    c.bandwidth_count = LIUQIN_BW_LEVELS;
    c.ddr_count = 3u;
    c.ddr_wait_mask = 0x7u;
    c.ddr_addresses[0] = in->sh0.address;
    c.ddr_addresses[1] = in->mc0.address;
    c.ddr_addresses[2] = in->acv.address;
    for (unsigned lvl = 0; lvl < LIUQIN_BW_LEVELS; ++lvl) {
        for (unsigned j = 0; j < 3; ++j)
            c.ddr_data[lvl][j] = kA730DdrData[lvl][j];
    }

    c.cnoc_count = 1u;
    c.cnoc_wait_mask = 0x1u;
    c.cnoc_addresses[0] = in->cn0_address;
    c.cnoc_data[0][0] = 0x40000000u;
    c.cnoc_data[1][0] = 0x60000001u;

    c.enable_ifpc = in->enable_ifpc;
    if (AdrenoHfiStartupValidate(&c))
        return AdrenoHfiStartupInvalid;
    *out = c;
    return AdrenoHfiStartupSuccess;
}

unsigned ShengGmuPerfVote(unsigned perf, unsigned *bandwidth)
{
    if (perf < 1u) perf = 1u;
    if (perf >= LIUQIN_GPU_OPPS) perf = LIUQIN_GPU_OPPS - 1u;
    if (bandwidth) *bandwidth = kGpuOppToBw[perf];
    return perf;
}
