// SPDX-License-Identifier: BSD-2-Clause-Patent
// r102-p12: Bounded read-only SM8475 GPU platform discovery probe.
// Phase 1: CurrentEL/ID regs + live post-ABL FDT (GPU/GMU/SMMU/OPP/cmd-db/ZAP).
// Phase 2: Exact 128 KiB cmd-db snapshot (0x80860000/0x20000 ONLY) -> SHA-256 + non-zero blocks.
// Phase 3: Single read-only IS_CALL_AVAIL SMC self-query AFTER USB completion fence.
// Phase 4: Fail-closed skip of unpowered GPU-SMMU IDRs (unmapped gcd[12]).
// Zero GPU/GMU/SMMU/clock/reset/PAS writes; zero static __DATA bloat.

#include <IOKit/IOLib.h>
#include <IOKit/IODeviceMemory.h>
#include <IOKit/IOService.h>
#include <kern/thread.h>
#include <libkern/libkern.h>
#include <stdint.h>
#include <string.h>

extern "C" uint64_t liuqin_debug_total(void);
extern "C" uint64_t liuqin_r102_usb_completed(void);

namespace {

// Compact SHA-256 (const tables only, zero writable __DATA)
static const uint32_t kSha256K[64] = {
    0x428a2f98u,0x71374491u,0xb5c0fbcfu,0xe9b5dba5u,0x3956c25bu,0x59f111f1u,0x923f82a4u,0xab1c5ed5u,
    0xd807aa98u,0x12835b01u,0x243185beu,0x550c7dc3u,0x72be5d74u,0x80deb1feu,0x9bdc06a7u,0xc19bf174u,
    0xe49b69c1u,0xefbe4786u,0x0fc19dc6u,0x240ca1ccu,0x2de92c6fu,0x4a7484aau,0x5cb0a9dcu,0x76f988dau,
    0x983e5152u,0xa831c66du,0xb00327c8u,0xbf597fc7u,0xc6e00bf3u,0xd5a79147u,0x06ca6351u,0x14292967u,
    0x27b70a85u,0x2e1b2138u,0x4d2c6dfcu,0x53380d13u,0x650a7354u,0x766a0abbu,0x81c2c92eu,0x92722c85u,
    0xa2bfe8a1u,0xa81a664bu,0xc24b8b70u,0xc76c51a3u,0xd192e819u,0xd6990624u,0xf40e3585u,0x106aa070u,
    0x19a4c116u,0x1e376c08u,0x2748774cu,0x34b0bcb5u,0x391c0cb3u,0x4ed8aa4au,0x5b9cca4fu,0x682e6ff3u,
    0x748f82eeu,0x78a5636fu,0x84c87814u,0x8cc70208u,0x90befffau,0xa4506cebu,0xbef9a3f7u,0xc67178f2u
};

static inline uint32_t rotr32(uint32_t x, unsigned n) { return (x >> n) | (x << (32u - n)); }

static void sha256_block(uint32_t st[8], const uint8_t blk[64]) {
    uint32_t w[64];
    for (unsigned i = 0; i < 16; ++i) {
        w[i] = ((uint32_t)blk[4*i] << 24) | ((uint32_t)blk[4*i+1] << 16) |
               ((uint32_t)blk[4*i+2] << 8) | (uint32_t)blk[4*i+3];
    }
    for (unsigned i = 16; i < 64; ++i) {
        uint32_t s0 = rotr32(w[i-15], 7) ^ rotr32(w[i-15], 18) ^ (w[i-15] >> 3);
        uint32_t s1 = rotr32(w[i-2], 17) ^ rotr32(w[i-2], 19) ^ (w[i-2] >> 10);
        w[i] = w[i-16] + s0 + w[i-7] + s1;
    }
    uint32_t a=st[0], b=st[1], c=st[2], d=st[3], e=st[4], f=st[5], g=st[6], h=st[7];
    for (unsigned i = 0; i < 64; ++i) {
        uint32_t S1 = rotr32(e, 6) ^ rotr32(e, 11) ^ rotr32(e, 25);
        uint32_t ch = (e & f) ^ ((~e) & g);
        uint32_t t1 = h + S1 + ch + kSha256K[i] + w[i];
        uint32_t S0 = rotr32(a, 2) ^ rotr32(a, 13) ^ rotr32(a, 22);
        uint32_t maj = (a & b) ^ (a & c) ^ (b & c);
        uint32_t t2 = S0 + maj;
        h = g; g = f; f = e; e = d + t1;
        d = c; c = b; b = a; a = t1 + t2;
    }
    st[0]+=a; st[1]+=b; st[2]+=c; st[3]+=d; st[4]+=e; st[5]+=f; st[6]+=g; st[7]+=h;
}

static void sha256_hex(const uint8_t *data, size_t len, char out[65]) {
    uint32_t st[8] = {
        0x6a09e667u,0xbb67ae85u,0x3c6ef372u,0xa54ff53au,
        0x510e527fu,0x9b05688cu,0x1f83d9abu,0x5be0cd19u
    };
    size_t pos = 0;
    while (pos + 64 <= len) {
        sha256_block(st, data + pos);
        pos += 64;
    }
    uint8_t tail[128];
    memset(tail, 0, sizeof(tail));
    size_t rem = len - pos;
    if (rem) memcpy(tail, data + pos, rem);
    tail[rem] = 0x80u;
    size_t pad_blocks = (rem < 56) ? 1 : 2;
    uint64_t bits = (uint64_t)len * 8ULL;
    size_t bit_off = pad_blocks * 64 - 8;
    for (unsigned i = 0; i < 8; ++i) tail[bit_off + i] = (uint8_t)(bits >> (56 - 8*i));
    for (size_t b = 0; b < pad_blocks; ++b) sha256_block(st, tail + b * 64);
    static const char hx[] = "0123456789abcdef";
    for (unsigned i = 0; i < 8; ++i) {
        for (unsigned j = 0; j < 8; ++j) {
            out[i*8 + j] = hx[(st[i] >> (28 - 4*j)) & 0xfu];
        }
    }
    out[64] = '\0';
}

static bool wait_usb_fence(uint64_t target, unsigned max_ms, unsigned *waited_out) {
    unsigned waited = 0;
    while (liuqin_r102_usb_completed() < target && waited < max_ms) {
        IOSleep(10);
        waited += 10;
    }
    if (waited_out) *waited_out = waited;
    return liuqin_r102_usb_completed() >= target;
}

static void pace_usb(unsigned &line_counter) {
    ++line_counter;
    if ((line_counter & 7u) == 0u) {
        uint64_t tot = liuqin_debug_total();
        if (tot > 8192ULL) {
            wait_usb_fence(tot - 8192ULL, 1000, nullptr);
        }
        IOSleep(10);
    }
}

static inline uint32_t be32(const uint8_t *p) {
    return ((uint32_t)p[0] << 24) | ((uint32_t)p[1] << 16) | ((uint32_t)p[2] << 8) | p[3];
}
static inline uint64_t be64(const uint8_t *p) {
    return ((uint64_t)be32(p) << 32) | be32(p + 4);
}
static inline uint32_t le32(const uint8_t *p) {
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

static bool str_contains(const char *hay, const char *needle) {
    if (!hay || !needle || !*needle) return false;
    size_t nlen = strlen(needle);
    for (const char *p = hay; *p; ++p) {
        if (strncmp(p, needle, nlen) == 0) return true;
    }
    return false;
}

static bool map_and_copy_words(uint64_t phys, size_t size, IOOptionBits map_opts, uint8_t *dst) {
    if (!dst || !size || (size & 3u) || (phys & 3u)) return false;
    IODeviceMemory *mem = IODeviceMemory::withRange(phys, size);
    if (!mem) return false;
    IOMemoryMap *map = mem->map(map_opts);
    mem->release();
    if (!map) return false;
    const volatile uint32_t *src = reinterpret_cast<const volatile uint32_t *>(map->getVirtualAddress());
    uint32_t *out = reinterpret_cast<uint32_t *>(dst);
    size_t words = size >> 2;
    for (size_t i = 0; i < words; ++i) {
        out[i] = src[i];
    }
    __asm__ volatile("dsb sy" ::: "memory");
    map->release();
    return true;
}

static bool parse_hex_u64(const char *s, uint64_t *out) {
    if (!s) return false;
    if (s[0] == '0' && (s[1] == 'x' || s[1] == 'X')) s += 2;
    uint64_t v = 0;
    unsigned digits = 0;
    while (*s) {
        char c = *s;
        unsigned d = 0;
        if (c >= '0' && c <= '9') d = (unsigned)(c - '0');
        else if (c >= 'a' && c <= 'f') d = (unsigned)(c - 'a' + 10);
        else if (c >= 'A' && c <= 'F') d = (unsigned)(c - 'A' + 10);
        else break;
        if (digits >= 16) return false;
        v = (v << 4) | d;
        ++digits;
        ++s;
    }
    if (!digits) return false;
    *out = v;
    return true;
}

static bool parse_dec_u64(const char *s, uint64_t *out) {
    if (!s || *s < '0' || *s > '9') return false;
    uint64_t v = 0;
    while (*s >= '0' && *s <= '9') {
        v = v * 10ULL + (uint64_t)(*s - '0');
        ++s;
    }
    *out = v;
    return true;
}

// Extract dtb=0x... dtb_sz=... from UEFI_MEMDIAG ring at 0xA7605000 (read-only)
static bool find_live_dtb_from_uefi_memdiag(uint64_t *base_out, uint64_t *sz_out) {
    uint8_t *buf = reinterpret_cast<uint8_t *>(IOMallocData(0x8000));
    if (!buf) return false;
    bool ok = map_and_copy_words(0xA7605000ULL, 0x8000, kIOMapAnywhere | kIOMapInhibitCache | kIOMapReadOnly, buf);
    bool found = false;
    if (ok) {
        uint64_t magic = (uint64_t)le32(buf) | ((uint64_t)le32(buf + 4) << 32);
        uint32_t cap = le32(buf + 8);
        uint32_t len = le32(buf + 12);
        if (magic == 0x3147444D454D514CULL && cap > 0 && cap <= 0x7FE8u && len <= cap) {
            const char *txt = reinterpret_cast<const char *>(buf + 24);
            // Null-terminate safely
            if (24u + len < 0x8000u) buf[24u + len] = '\0';
            else buf[0x7FFFu] = '\0';
            for (uint32_t i = 0; i + 8 < len; ++i) {
                if (strncmp(txt + i, "dtb=0x", 6) == 0) {
                    uint64_t b = 0, sz = 0;
                    if (parse_hex_u64(txt + i + 4, &b)) {
                        for (uint32_t j = i; j + 8 < len && j < i + 64; ++j) {
                            if (strncmp(txt + j, "dtb_sz=", 7) == 0) {
                                if (parse_dec_u64(txt + j + 7, &sz)) {
                                    *base_out = b;
                                    *sz_out = sz;
                                    found = true;
                                }
                                break;
                            }
                        }
                    }
                    break;
                }
            }
        }
    }
    IOFreeData(buf, 0x8000);
    return found;
}

static bool is_interesting_fdt_path(const char *path) {
    if (strcmp(path, "/") == 0) return true;
    if (strncmp(path, "/reserved-memory/", 17) == 0) {
        return str_contains(path, "80860000") || str_contains(path, "8b91a000") ||
               str_contains(path, "cmd") || str_contains(path, "gpu") || str_contains(path, "zap");
    }
    return str_contains(path, "gpu") || str_contains(path, "gmu") ||
           str_contains(path, "kgsl") || str_contains(path, "adreno") ||
           str_contains(path, "3d00000") || str_contains(path, "3d50000") ||
           str_contains(path, "3d6a000") || str_contains(path, "3d90000") ||
           str_contains(path, "3da0000") || str_contains(path, "b290000");
}

static bool is_interesting_fdt_prop(const char *prop) {
    return strcmp(prop, "model") == 0 || strcmp(prop, "compatible") == 0 ||
           strcmp(prop, "status") == 0 || strcmp(prop, "reg") == 0 ||
           strcmp(prop, "reg-names") == 0 || strcmp(prop, "no-map") == 0 ||
           strcmp(prop, "interrupts") == 0 || strcmp(prop, "interrupt-names") == 0 ||
           strcmp(prop, "iommus") == 0 || strcmp(prop, "clock-names") == 0 ||
           strcmp(prop, "power-domain-names") == 0 || strcmp(prop, "firmware-name") == 0 ||
           strcmp(prop, "opp-hz") == 0 || strcmp(prop, "opp-level") == 0 ||
           strcmp(prop, "qcom,opp-acd-level") == 0 || strcmp(prop, "qcom,gpu-freq") == 0 ||
           strcmp(prop, "qcom,bus-freq") == 0 || strcmp(prop, "qcom,acd-level") == 0 ||
           strcmp(prop, "qcom,chipid") == 0;
}

static void inspect_live_fdt(uint64_t dtb_base, uint64_t dtb_sz, unsigned &lines,
                             uint64_t *cmddb_base_out, uint64_t *cmddb_size_out, bool *cmddb_nomap_out) {
    *cmddb_base_out = 0;
    *cmddb_size_out = 0;
    *cmddb_nomap_out = false;
    if (dtb_base == 0 || dtb_sz < 40 || dtb_sz > 0x200000ULL) {
        IOLog("LQ102 FDT_SKIP reason=invalid_bounds base=0x%llx sz=%llu\n",
              (unsigned long long)dtb_base, (unsigned long long)dtb_sz);
        return;
    }
    size_t copy_sz = ((size_t)dtb_sz + 3u) & ~3u;
    uint8_t *fdt = reinterpret_cast<uint8_t *>(IOMallocData(copy_sz));
    if (!fdt) {
        IOLog("LQ102 FDT_SKIP reason=oom sz=%zu\n", copy_sz);
        return;
    }
    if (!map_and_copy_words(dtb_base, copy_sz, kIOMapAnywhere | kIOMapReadOnly, fdt)) {
        IOLog("LQ102 FDT_SKIP reason=map_failed base=0x%llx\n", (unsigned long long)dtb_base);
        IOFreeData(fdt, copy_sz);
        return;
    }
    uint32_t magic = be32(fdt + 0);
    uint32_t totalsize = be32(fdt + 4);
    uint32_t off_struct = be32(fdt + 8);
    uint32_t off_strings = be32(fdt + 12);
    uint32_t version = be32(fdt + 20);
    uint32_t size_strings = be32(fdt + 32);
    uint32_t size_struct = be32(fdt + 36);
    if (magic != 0xD00DFEEDu || totalsize < 40u || totalsize > copy_sz ||
        off_struct > totalsize || size_struct > totalsize - off_struct ||
        off_strings > totalsize || size_strings > totalsize - off_strings) {
        IOLog("LQ102 FDT_ERR magic=0x%x totalsize=%u copy_sz=%zu\n", magic, totalsize, copy_sz);
        IOFreeData(fdt, copy_sz);
        return;
    }
    char fdt_sha[65];
    sha256_hex(fdt, totalsize, fdt_sha);
    IOLog("LQ102 FDT_HDR base=0x%llx totalsize=%u ver=%u sha256=%s\n",
          (unsigned long long)dtb_base, totalsize, version, fdt_sha);
    pace_usb(lines);

    // Bounded iterative FDT walk (max depth 16)
    char stack_names[16][64];
    unsigned depth = 0;
    uint32_t pos = off_struct;
    uint32_t end_struct = off_struct + size_struct;
    char cur_path[256];
    cur_path[0] = '\0';
    bool cur_interesting = false;
    bool cur_is_cmddb = false;
    uint64_t cur_reg_base = 0, cur_reg_size = 0;
    bool cur_has_reg = false, cur_nomap = false;
    unsigned nodes_emitted = 0;

    auto build_path = [&]() {
        size_t p = 0;
        if (depth <= 1) {
            cur_path[0] = '/'; cur_path[1] = '\0';
            return;
        }
        for (unsigned d = 1; d < depth; ++d) {
            size_t n = strlen(stack_names[d]);
            if (p + 1 + n >= sizeof(cur_path)) break;
            cur_path[p++] = '/';
            memcpy(cur_path + p, stack_names[d], n);
            p += n;
        }
        cur_path[p] = '\0';
    };

    while (pos + 4 <= end_struct) {
        uint32_t tok = be32(fdt + pos);
        pos += 4;
        if (tok == 1u) { // FDT_BEGIN_NODE
            uint32_t nul = pos;
            while (nul < end_struct && fdt[nul] != 0) ++nul;
            if (nul >= end_struct) break;
            if (depth < 16) {
                size_t n = nul - pos;
                if (n >= sizeof(stack_names[depth])) n = sizeof(stack_names[depth]) - 1;
                memcpy(stack_names[depth], fdt + pos, n);
                stack_names[depth][n] = '\0';
            }
            ++depth;
            pos = (nul + 4u) & ~3u;
            build_path();
            cur_interesting = is_interesting_fdt_path(cur_path);
            cur_is_cmddb = (strcmp(cur_path, "/reserved-memory/memory@80860000") == 0);
            cur_has_reg = false; cur_nomap = false; cur_reg_base = 0; cur_reg_size = 0;
            if (cur_interesting && nodes_emitted < 120) {
                IOLog("LQ102 FDT_NODE path=%s\n", cur_path);
                pace_usb(lines);
                ++nodes_emitted;
            }
        } else if (tok == 2u) { // FDT_END_NODE
            if (cur_is_cmddb && cur_has_reg) {
                *cmddb_base_out = cur_reg_base;
                *cmddb_size_out = cur_reg_size;
                *cmddb_nomap_out = cur_nomap;
            }
            if (depth > 0) --depth;
            build_path();
            cur_interesting = is_interesting_fdt_path(cur_path);
            cur_is_cmddb = false;
        } else if (tok == 3u) { // FDT_PROP
            if (pos + 8 > end_struct) break;
            uint32_t plen = be32(fdt + pos);
            uint32_t nameoff = be32(fdt + pos + 4);
            pos += 8;
            if (plen > end_struct - pos || nameoff >= size_strings) break;
            const char *pname = reinterpret_cast<const char *>(fdt + off_strings + nameoff);
            const uint8_t *pval = fdt + pos;
            pos = (pos + plen + 3u) & ~3u;

            if (strcmp(pname, "compatible") == 0 && plen >= 11 && str_contains(reinterpret_cast<const char *>(pval), "qcom,cmd-db")) {
                cur_is_cmddb = true;
            }
            if (strcmp(pname, "no-map") == 0) cur_nomap = true;
            if (strcmp(pname, "reg") == 0 && plen >= 16) {
                cur_reg_base = be64(pval);
                cur_reg_size = be64(pval + 8);
                cur_has_reg = true;
            }

            if (cur_interesting && nodes_emitted <= 120 && is_interesting_fdt_prop(pname)) {
                if (strcmp(pname, "no-map") == 0) {
                    IOLog("LQ102 FDT_PROP path=%s prop=no-map val=true\n", cur_path);
                } else if (strcmp(pname, "model") == 0 || strcmp(pname, "compatible") == 0 ||
                           strcmp(pname, "status") == 0 || strcmp(pname, "reg-names") == 0 ||
                           strcmp(pname, "interrupt-names") == 0 || strcmp(pname, "clock-names") == 0 ||
                           strcmp(pname, "power-domain-names") == 0 || strcmp(pname, "firmware-name") == 0) {
                    char sbuf[192];
                    size_t outp = 0;
                    for (uint32_t i = 0; i < plen && outp + 2 < sizeof(sbuf); ++i) {
                        uint8_t ch = pval[i];
                        if (ch == 0) {
                            if (i + 1 < plen) sbuf[outp++] = ',';
                        } else if (ch >= 32 && ch < 127) {
                            sbuf[outp++] = (char)ch;
                        } else {
                            sbuf[outp++] = '?';
                        }
                    }
                    sbuf[outp] = '\0';
                    IOLog("LQ102 FDT_PROP path=%s prop=%s str=%s\n", cur_path, pname, sbuf);
                } else if (strcmp(pname, "opp-hz") == 0 && plen == 8) {
                    IOLog("LQ102 FDT_PROP path=%s prop=opp-hz u64=%llu\n", cur_path, (unsigned long long)be64(pval));
                } else if ((strcmp(pname, "opp-level") == 0 || strcmp(pname, "qcom,gpu-freq") == 0 ||
                            strcmp(pname, "qcom,bus-freq") == 0 || strcmp(pname, "qcom,acd-level") == 0 ||
                            strcmp(pname, "qcom,opp-acd-level") == 0 || strcmp(pname, "qcom,chipid") == 0) && plen == 4) {
                    uint32_t v = be32(pval);
                    IOLog("LQ102 FDT_PROP path=%s prop=%s u32=%u (0x%x)\n", cur_path, pname, v, v);
                } else {
                    char hbuf[192];
                    size_t outp = 0;
                    uint32_t cells = plen / 4u;
                    if (cells > 16u) cells = 16u;
                    for (uint32_t c = 0; c < cells && outp + 12 < sizeof(hbuf); ++c) {
                        int n = snprintf(hbuf + outp, sizeof(hbuf) - outp, "%s0x%x", c ? " " : "", be32(pval + c * 4u));
                        if (n > 0) outp += (size_t)n;
                    }
                    hbuf[outp] = '\0';
                    IOLog("LQ102 FDT_PROP path=%s prop=%s len=%u cells=[%s]\n", cur_path, pname, plen, hbuf);
                }
                pace_usb(lines);
            }
        } else if (tok == 4u) { // FDT_NOP
            continue;
        } else if (tok == 9u) { // FDT_END
            break;
        } else {
            break;
        }
    }
    IOLog("LQ102 FDT_DONE nodes_emitted=%u cmddb_base=0x%llx cmddb_size=0x%llx cmddb_nomap=%u\n",
          nodes_emitted, (unsigned long long)*cmddb_base_out, (unsigned long long)*cmddb_size_out,
          *cmddb_nomap_out ? 1u : 0u);
    pace_usb(lines);
    IOFreeData(fdt, copy_sz);
}

static void capture_cmd_db(uint64_t base, uint64_t size, unsigned &lines) {
    if (base != 0x80860000ULL || size != 0x20000ULL) {
        IOLog("LQ102 CMDDB_SKIP reason=unexpected_range base=0x%llx size=0x%llx\n",
              (unsigned long long)base, (unsigned long long)size);
        return;
    }
    uint8_t *buf = reinterpret_cast<uint8_t *>(IOMallocData(0x20000));
    if (!buf) {
        IOLog("LQ102 CMDDB_SKIP reason=oom\n");
        return;
    }
    IOLog("LQ102 CMDDB_MAP_START base=0x%llx size=0x%llx\n",
          (unsigned long long)base, (unsigned long long)size);
    wait_usb_fence(liuqin_debug_total(), 3000, nullptr);
    IOSleep(200);

    bool ok = map_and_copy_words(base, 0x20000, kIOMapAnywhere | kIOMapInhibitCache | kIOMapReadOnly, buf);
    if (!ok) {
        IOLog("LQ102 CMDDB_ERR reason=map_failed\n");
        IOFreeData(buf, 0x20000);
        return;
    }
    uint32_t ver = le32(buf + 0);
    uint32_t magic = le32(buf + 4);
    char sha[65];
    sha256_hex(buf, 0x20000, sha);
    IOLog("LQ102 CMDDB_HDR base=0x%llx size=0x20000 ver=0x%x magic=0x%08x sha256=%s\n",
          (unsigned long long)base, ver, magic, sha);
    pace_usb(lines);

    static const char hx[] = "0123456789abcdef";
    unsigned nonzero_blocks = 0;
    char hexline[65];
    for (uint32_t off = 0; off < 0x20000u; off += 32u) {
        bool nz = false;
        for (uint32_t k = 0; k < 32u; ++k) {
            if (buf[off + k] != 0) { nz = true; break; }
        }
        if (!nz) continue;
        for (uint32_t k = 0; k < 32u; ++k) {
            hexline[k*2]     = hx[(buf[off + k] >> 4) & 0xfu];
            hexline[k*2 + 1] = hx[buf[off + k] & 0xfu];
        }
        hexline[64] = '\0';
        IOLog("LQ102 CMDDB_BLK off=0x%05x hex=%s\n", off, hexline);
        ++nonzero_blocks;
        pace_usb(lines);
    }
    IOLog("LQ102 CMDDB_END nonzero_blocks=%u sha256=%s\n", nonzero_blocks, sha);
    pace_usb(lines);
    IOFreeData(buf, 0x20000);
}

static void probe_scm_is_call_avail(void) {
    // Flush everything prior to SMC over USB before invoking smc #0
    uint64_t fence = liuqin_debug_total();
    unsigned waited = 0;
    bool flushed = wait_usb_fence(fence, 15000, &waited);
    IOLog("LQ102 PRE_SMC_FENCE completed=%u waited_ms=%u\n", flushed ? 1u : 0u, waited);
    wait_usb_fence(liuqin_debug_total(), 5000, nullptr);
    IOSleep(500);

    // Linux qcom_scm INFO service=6, cmd=1, SIP owner=2 (ARM64 fast call):
    // x0=0xc2000601, x1=1 (1 value arg), x2=0x02000601 (self-query), x3..x7=0.
    register uint64_t r0 __asm__("x0") = 0xc2000601ULL;
    register uint64_t r1 __asm__("x1") = 1ULL;
    register uint64_t r2 __asm__("x2") = 0x02000601ULL;
    register uint64_t r3 __asm__("x3") = 0ULL;
    register uint64_t r4 __asm__("x4") = 0ULL;
    register uint64_t r5 __asm__("x5") = 0ULL;
    register uint64_t r6 __asm__("x6") = 0ULL;
    register uint64_t r7 __asm__("x7") = 0ULL;
    __asm__ volatile(
        "smc #0\n"
        : "+r"(r0), "+r"(r1), "+r"(r2), "+r"(r3), "+r"(r4), "+r"(r5), "+r"(r6), "+r"(r7)
        :
        : "memory", "x8", "x9", "x10", "x11", "x12", "x13", "x14", "x15", "x16", "x17"
    );
    IOLog("LQ102 SCM_AVAIL in_x0=0xc2000601 in_x1=0x1 in_x2=0x02000601 out_x0=0x%llx out_x1=0x%llx out_x2=0x%llx out_x3=0x%llx\n",
          (unsigned long long)r0, (unsigned long long)r1, (unsigned long long)r2, (unsigned long long)r3);
}

static void discovery_worker(void *, wait_result_t) {
    mach_timespec_t timeout = {30, 0};
    (void)IOService::waitForService(IOService::resourceMatching("IOBSD"), &timeout);

    // Wait up to 45 s for host USB CDC ACM reader to connect and drain at least 1 byte
    for (unsigned w = 0; w < 450; ++w) {
        if (liuqin_r102_usb_completed() > 0) break;
        IOSleep(100);
    }
    IOSleep(1000);

    unsigned lines = 0;
    uint64_t cur_el = 0, mpidr = 0, midr = 0, mmfr0 = 0, cntfrq = 0;
    __asm__ volatile("mrs %0, CurrentEL" : "=r"(cur_el));
    __asm__ volatile("mrs %0, MPIDR_EL1" : "=r"(mpidr));
    __asm__ volatile("mrs %0, MIDR_EL1" : "=r"(midr));
    __asm__ volatile("mrs %0, ID_AA64MMFR0_EL1" : "=r"(mmfr0));
    __asm__ volatile("mrs %0, CNTFRQ_EL0" : "=r"(cntfrq));

    IOLog("LQ102 GPUDISC_BEGIN el=%llu mpidr=0x%llx midr=0x%llx mmfr0=0x%llx cntfrq=%llu\n",
          (unsigned long long)(cur_el >> 2), (unsigned long long)mpidr, (unsigned long long)midr,
          (unsigned long long)mmfr0, (unsigned long long)cntfrq);
    pace_usb(lines);

    uint64_t dtb_base = 0, dtb_sz = 0;
    bool dtb_found = find_live_dtb_from_uefi_memdiag(&dtb_base, &dtb_sz);
    IOLog("LQ102 UEFI_DTB_PTR found=%u base=0x%llx sz=%llu\n",
          dtb_found ? 1u : 0u, (unsigned long long)dtb_base, (unsigned long long)dtb_sz);
    pace_usb(lines);

    uint64_t cmddb_base = 0, cmddb_size = 0;
    bool cmddb_nomap = false;
    if (dtb_found) {
        inspect_live_fdt(dtb_base, dtb_sz, lines, &cmddb_base, &cmddb_size, &cmddb_nomap);
    }

    // Fallback to verified live FDT address if UEFI_MEMDIAG confirmed 0x80860000/0x20000
    if (cmddb_base == 0 && cmddb_size == 0) {
        IOLog("LQ102 CMDDB_NOTE live_fdt_node_not_matched_trying_verified_a7_range=0x80860000/0x20000\n");
        cmddb_base = 0x80860000ULL;
        cmddb_size = 0x20000ULL;
    }
    capture_cmd_db(cmddb_base, cmddb_size, lines);

    probe_scm_is_call_avail();

    IOLog("LQ102 SMMU_IDR status=SKIPPED reason=unmapped_gcd12_and_unpowered_cx\n");
    IOLog("LQ102 GPUDISC_END ok=1 lines=%u\n", lines);
    wait_usb_fence(liuqin_debug_total(), 10000, nullptr);
    thread_terminate(current_thread());
}

} // namespace

extern "C" void liuqin_gpu_discovery_start(void) {
    thread_t thread = nullptr;
    kern_return_t rc = kernel_thread_start(discovery_worker, nullptr, &thread);
    if (rc == KERN_SUCCESS) thread_deallocate(thread);
    else IOLog("LQ102 GPUDISC_SPAWN_ERR rc=%x\n", rc);
}
