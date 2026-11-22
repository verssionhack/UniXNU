/* SPDX-License-Identifier: BSD-2-Clause-Patent */
/* SM8475 / Adreno 730.1 GMU rules for ShengGmu.c.
 * Sources:
 *   - Live post-ABL FDT (r102-p12, sha256=5dfc33e4...): gmu@3d6a000/0x35000, rscc@3d50000/0x10000, gmu_pdc@b290000/0x10000,
 *     gpu@3d00000/0x40000, cx_mem@3d9e000/0x1000.
 *   - linux-release-clean/drivers/gpu/drm/msm/adreno/{a6xx_gmu.c,a6xx_catalog.c,a6xx_gmu.xml}:
 *     chip_id=0x07030001, fw_chip_id=0x07030100, HIDDEN_TCS_CMD0_DATA+4=0x80000000, RSCC_SEQ_MEM_0_DRV0=0x180 (0x600).
 *   - gmu_gen70000.bin (57272 B, sha256=b2d3f0e2a98fd6259ab9ffef16df63265542e6cc9a970d53d476e823d432042a).
 */
#include <stdint.h>
#include <stddef.h>
#define REG_GMU_CM3_ITCM_START UINT32_C(0x1b400)
#define REG_GMU_CM3_DTCM_START UINT32_C(0x1c400)
#define REG_GMU_CM3_SYSRESET UINT32_C(0x1f800)
#define REG_GMU_CM3_BOOT_CONFIG UINT32_C(0x1f801)
#define REG_GMU_CM3_FW_INIT_RESULT UINT32_C(0x1f81c)
#define REG_GMU_CM3_CFG UINT32_C(0x1f82d)
#define REG_GMU_HFI_QTBL_ADDR UINT32_C(0x1f985)
#define REG_GMU_HFI_QTBL_INFO UINT32_C(0x1f984)
#define REG_GMU_HFI_CTRL_INIT UINT32_C(0x1f986)
#define REG_GMU_HFI_CTRL_STATUS UINT32_C(0x1f980)
#define REG_GMU_HOST2GMU_INTR_SET UINT32_C(0x1f994)
#define REG_GMU_SYS_BUS_CONFIG UINT32_C(0x1f40f)
#define REG_GMU_ICACHE_CONFIG UINT32_C(0x1f400)
#define REG_GMU_DCACHE_CONFIG UINT32_C(0x1f401)
#define REG_GMU_AHB_FENCE_RANGE_0 UINT32_C(0x23b11)
#define REG_GMU_GMU2HOST_INTR_INFO UINT32_C(0x1f992)
#define REG_GMU_AO_HOST_INTERRUPT_STATUS UINT32_C(0x23b05)
#define REG_GPU_GMU_CX_GMU_CX_FALNEXT_INTF UINT32_C(0x1f8f1)
#define REG_GPU_GMU_CX_GMU_CX_FAL_INTF UINT32_C(0x1f8f0)
#define REG_GMU_GENERAL_8 UINT32_C(0x1f9cd)
#define REG_GMU_GENERAL_9 UINT32_C(0x1f9ce)
#define REG_GMU_GENERAL_10 UINT32_C(0x1f9cf)
#define REG_GPU_RSCC_RSC_STATUS0_DRV0 UINT32_C(0x4)
#define REG_RSCC_PDC_SLAVE_ID_DRV0 UINT32_C(0xb)
#define REG_RSCC_HIDDEN_TCS_CMD0_ADDR UINT32_C(0xd)
#define REG_RSCC_HIDDEN_TCS_CMD0_DATA UINT32_C(0xe)
#define REG_RSCC_OVERRIDE_START_ADDR UINT32_C(0x100)
#define REG_RSCC_PDC_SEQ_START_ADDR UINT32_C(0x8)
#define REG_RSCC_PDC_MATCH_VALUE_LO UINT32_C(0x9)
#define REG_RSCC_PDC_MATCH_VALUE_HI UINT32_C(0xa)
#define REG_RSCC_SEQ_BUSY_DRV0 UINT32_C(0x101)
#define REG_RSCC_SEQ_MEM_0_DRV0 UINT32_C(0x180)
#define REG_CX_MISC_TCM_RET_CNTL UINT32_C(0x39)
#define REG_GBIF_QSB_SIDE0 UINT32_C(0x3c03)
#define REG_PDC_GPU_SEQ_START_ADDR UINT32_C(0x1148)
#define REG_PDC_GPU_ENABLE_PDC UINT32_C(0x1140)

#define SHENG_GMU_CHIP_ID UINT32_C(0x07030001)
#define SHENG_GMU_FW_CHIP_ID UINT32_C(0x07030100)
#define SHENG_GMU_CORE_GPU_DELTA 0x6a000u
#define SHENG_GMU_FIRMWARE_BYTES 57272u
#define SHENG_GMU_AO_FATAL_MASK 0x29u
#define SHENG_GMU_CM3_FATAL_MASK 0x800000u

static const uint8_t sheng_gmu_firmware_sha256[32] = {
    0xb2,0xd3,0xf0,0xe2,0xa9,0x8f,0xd6,0x25,0x9a,0xb9,0xff,0xef,0x16,0xdf,0x63,0x26,
    0x55,0x42,0xe6,0xcc,0x9a,0x97,0x0d,0x53,0xd4,0x76,0xe8,0x23,0xd4,0x32,0x04,0x2a
};
static const uint64_t sheng_gmu_window_physical[5] = {
    0x3d6a000ULL, 0x3d50000ULL, 0xb290000ULL, 0x3d00000ULL, 0x3d9e000ULL
};
static const size_t sheng_gmu_window_bytes[5] = {
    0x35000u, 0x10000u, 0x10000u, 0x40000u, 0x1000u
};
typedef struct { unsigned window; size_t byte_offset; uint32_t value; } ShengGmuSetupWrite;
#define SHENG_GMU_RSC_SETUP_COUNT 19u
static const ShengGmuSetupWrite sheng_gmu_rsc_setup[19] = {
    {1, 0x10, 0x1000000u},
    {1, 0x2c, 0x1u},
    {1, 0x38, 0x0u},
    {1, 0x34, 0x0u},
    {1, 0x40, 0x0u},
    {1, 0x3c, 0x0u},
    {1, 0x48, 0x80000000u}, /* A730 (non-A740): 0x80000000 per a6xx_gmu.c:606 */
    {1, 0x44, 0x0u},
    {1, 0x400, 0x0u},
    {1, 0x20, 0x4520u},
    {1, 0x24, 0x4510u},
    {1, 0x28, 0x4514u},
    {1, 0x600, 0xeaaae5a0u}, /* REG_A6XX_RSCC_SEQ_MEM_0_DRV0 (0x180 * 4 = 0x600) */
    {1, 0x604, 0xe1a1ebabu},
    {1, 0x608, 0xa2e0a581u},
    {1, 0x60c, 0xecac82e2u},
    {1, 0x610, 0x0020edadu},
    {2, 0x4520, 0x0u},       /* PDC_GPU_SEQ_START_ADDR (0x1148 * 4) */
    {2, 0x4500, 0x80000001u},/* PDC_GPU_ENABLE_PDC (0x1140 * 4) */
};
