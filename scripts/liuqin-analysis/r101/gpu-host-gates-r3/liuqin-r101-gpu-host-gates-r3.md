# r101 GPU Host Gates r3: Phase 0 Handoff, SM8475 cmd-db/HFI Oracle, and Layout Budget Attribution

Date: 2026-11-21. Scope: **host-only** completion of remaining Milestone 1 host-qualifiable prerequisites in isolated revision `gpu-host-gates-r3`.
No A730/XNU driver edits, no boot image/payload emission, no device/fastboot commands, no `owner.key` access, and no modification to any previously frozen evidence or scripts.
Standing holds on **A730/XNU driver edits** and **graphics hardware boots** remain **ACTIVE**; `native_reader_validated=false` and the `EL0 TRAP=0` caveat remain unchanged.

Labels: **hardware-measured** (from frozen A7 `usb.log`), **host-measured**, **source-verified**, **inference**, **(verify)**.

---

## Executive Summary

1. **Phase 0 DT/ADT/UEFI_MEMDIAG Handoff Audit (`phase0-handoff-and-dtb-parity.json`):**
   - **Hardware-measured:** Frozen A7 `UEFI_MEMDIAG` already establishes `CurrentEL=1` (`el=1`, `tcr=0x280803518`, `sctlr=0x30D0198D`, `mmfr0=0x22200101122`) at UEFI→DarwinBoot handoff (does **not** identify EL2 hypervisor or SMC routing).
   - **Hardware-measured + host-measured:** ABL expanded the live post-ABL FDT to **`900,793 B` at `0xACCFE000`** (`4.07×` A7's packed `liuqin-cape.dtb` `221,452 B`, `7.26×` compiled Linux `liuqin-linux.dtb` `124,152 B`). Live FDT resides in UEFI reserved DRAM (`gcd[35]` `0xA7000000..0xB8000000`, DarwinBoot EFI `md` `t=0` `0xA8000000..0xBAB00000`), outside XNU's 4 GiB high DRAM (`0x840004000..0x940004000`). Frozen A7 `kernel.macho.adt` (`22` nodes) contains **zero** live-FDT pointer and **zero** GPU/GMU/SMMU/cmd-db/ZAP nodes — establishing a concrete Phase 0/1 handoff gap that a future read-only probe must bridge.
   - **Hardware-measured + source-verified:** Live post-ABL FDT confirms exact `no-map` reservations for `cmd-db` (`0x80860000`, `0x20000` inside `gcd[26]` / DarwinBoot `t=0` `attr=0x1` UC `0x80640000..0x808A0000`) and ZAP (`0x8b91a000`, `0x2000` inside `gcd[30]`). Host-measured `a730_zap.mbn` (`11,608 B` ELF32) has its single `PT_LOAD` (`ph[1]`) at rel `0x1000..0x18bc` (`2,236 B`, page-rounded `0x2000`), fitting the `0x2000` carveout (`ph[2]` `0xd58 B` is the non-`PT_LOAD` hash/cert segment).
   - **Hardware-measured:** All GPU/GMU/RSCC/GPUCC/GPU-SMMU MMIO (`0x03d00000..0x03de0000`) sit inside unmapped UEFI GCD gap `gcd[12]` (`t=0`, `0x1FF0000..0x8800000`, `attr=0x0`), while GMU PDC (`0x0b290000`) sits inside UEFI mapped MMIO `gcd[17]` (`t=3`, `0xB000000..0x10000000`, `attr=0x4001`). Combined with `UniXNU-liuqin/board.toml` noting APPS SMMU (`0x15000000`) caused an external abort on first EL1 read, Phase 4 MUST skip GPU-SMMU IDR reads unless CX power, 6 clocks, and EL2/TZ read safety are proven.
   - **Source-verified OPP discrepancy `(verify)`:** In pinned `linux-release-clean`, `sm8475.dtsi:64-121` comments out the 13-level SM8475 GPU OPP table (`220..900 MHz`, `MIN_SVS..TURBO_L1`), so compiled `sm8475-xiaomi-liuqin.dtb` (and A7's packed `liuqin-cape.dtb`) inherit `sm8450.dtsi`'s 12-level table (`220..818 MHz`, `LOW_SVS_D1..TURBO`) + 2 GMU OPPs (`200/500 MHz`). Live post-ABL FDT inspection in Phase 1 is needed to confirm the active board OPP set.

2. **Phase 2 Host-Side SM8475 cmd-db Parser & ASan+UBSan HFI Oracle (`sm8475_cmddb_tool.py`, `sm8475-cmddb-and-votes-oracle.json`):**
   - **Source-verified:** Unlike A740 (dynamic BCM calculation via `info->bcms` / `AdrenoHfiBuildBandwidth`), Linux `a6xx_catalog.c:1371` gives A730 **no `.bcms` array**, and `a6xx_hfi.c:a730_build_bw_table()` emits 12 static DDR rows (`SH0`/`MC0`/`ACV`, `wait_mask=0x7`) + 2 CNOC rows (`CN0`, `wait_mask=0x1`) populated with live `cmd-db` addresses.
   - **Host-measured:** Built reusable fail-closed Phase 2 host parser `sm8475_cmddb_tool.py` (exact 128 KiB bounds, magic/version/slave/duplicate/span-overlap checks, authoritative `gmxc.lvl` presence vs absence distinction, provenance-preserving GX/CX ARC vote words, static A730 BW table).
   - **Host-measured:** Cross-verified `sm8475_cmddb_tool.py` against a native host C oracle compiled with `-std=c11 -O2 -Wall -Wextra -Werror -fsanitize=address,undefined` linking Linux `cmd-db.c` binary lookup + `kits/AdrenoFirmware/{AdrenoHfiVotes.c,AdrenoHfiStartup.c}`:
     - **4/4 positive matrix cases bit-exact** (`gmxc.lvl` present & authoritatively absent × both 13-entry active `sm8450` and 14-entry commented `sm8475` GPU OPP tables).
     - `AdrenoHfiStartupValidate()` and `AdrenoHfiStartupEncode()` (Performance 58 words, Bandwidth 159 words, CoreStart 1 word, Start 0 words; ACD/IFPC disabled and cleanly refused) all **PASS** under ASan+UBSan.
     - **23/23 negative/corruption controls rejected fail-closed.**
   - **Caveat `(verify)`:** All inputs are synthetic host fixtures; real liuqin 128 KiB `cmd-db` bytes remain uncaptured until Phase 2 hardware qualification.

3. **Byte-for-Byte `first_const_vma` & `__DATA` Budget Attribution (`const-and-data-budget-audit.json`):**
   - **Host-measured (`first_const_vma` `-1,376 B` shift):** Frozen A7 `__TEXT` (`0x1cc000`, `0xfffffff007004000..0xfffffff0071d0000`) ends its last section (`__eh_frame`) at `0xfffffff0071cd000`, leaving `12,288 B` (`3 × 4 KiB`) unused trailing space before the 16 KiB segment end. `ld64` packs `__TEXT` backwards from 4 KiB boundaries. Adding the `a730blobs_plus_smmu` closure contributed `5,814 B` raw non-exec `__TEXT` (`NativeAdreno.o` `2,693 B`, `ShengGmu.kit.o` `664 B`, `NativeAdrenoSmmuService.o` `377 B`, `NativeAdrenoGmuService.o` `346 B`, `NativeAdrenoSha256.o` `304 B`, `NativeAdrenoPublish.o` `286 B`, etc.). After `~342 B` of `ld64` cstring deduplication/alignment (`5,814 - 5,472`), this expanded the 4 KiB tail by `4,096 B` + consumed `1,376 B` from the leading header pad (`header_gap` `2,000 → 624 B`; `const_vma` floor margin `1,760 → 384 B`).
     - **Non-monotonic wrap warning:** Adding `385..624 B` more non-exec `__TEXT` will trip the `0xfffffff007005900` floor; adding `>624 B` triggers the next 4 KiB tail step inside `0x1cc000` and jumps `first_const_vma` back up by `~3.5 KiB`.
   - **Host-measured (`__DATA` `+16,384 B` page crossing):** Frozen A7 `__DATA` (`0x27c000`) had `6,896 B` free in its last 16 KiB page. Added KMD objects contributed **`20,428 B`** writable `__DATA` (`__common` `17,744 B`, `__bss` `2,412 B`, `__data` `208 B`, `__mod_init_func` `32 B`, `__auth_ptr` `32 B`), dominated by:
     - `NativeAdrenoPublish.o`: `9,912 B`
     - `NativeAdrenoSubmit.o`: `3,188 B`
     - `NativeAdrenoPreempt.o`: `2,180 B`
     - `NativeAdrenoRing.o`: `1,908 B`
     - `NativeAdrenoUserClient.o`: `1,752 B`
     - `NativeAdrenoMemory.o`: `588 B`
     - Net overflow into the new 16 KiB page (`0x280000`) is `13,532 B`, leaving `~2.8 KiB` in `0x280000` + `16,384 B` in the last policy page before `0x284000` (`com.apple.kec.Libm`). Keeping future A730 static tables `const` (`__DATA_CONST`, `404,072 B` slack) and `cmd-db` snapshots heap-allocated (`IOMallocData(0x20000)`) is essential.
   - **Host-measured (Tier-1 observer static symbol inventory in frozen A7 `nm.txt`):** Slid emitted-fileset segment mapping (`+0x1f000000000`) classifies all 50 `liuqin_r10*`/`r10*` observer symbols cleanly:
     - Tier-1 `clocksyncd`/TimeSync (`8` symbols): `__TEXT_EXEC` `3,748 B` (3), `__TEXT` `323 B` (2), `__DATA_CONST` `144 B` (1), `__DATA` `24 B` (2: `_r104_main_base`, `_r105_requests`).
     - Retained/shared observer (`42` symbols): `__TEXT_EXEC` `19,828 B` (19), `__DATA` `3,552 B` (19), `__BOOTDATA` `72 B` (3), `__TEXT` `16 B` (1).
     - **Caveat:** Symbol-to-next-symbol spans are static upper bounds only (inlining, cstring dedup, and alignment mean **no reclaimed capacity is claimed without a rebuild**). Notably, Tier-1 retirement targets almost no static `__DATA` (`24 B`), so `__DATA` headroom management must focus on KMD static globals (`NativeAdrenoPublish.o` etc.).

---

## Gate Status After `gpu-host-gates-r3`

| Gate / Workstream | Status | Notes |
| --- | --- | --- |
| Reference KMD compile (`-Werror`), real arm64e `ld64` link, `XnuPrelink` fileset + AES gate (r2) | **HOST-PASSED** (with 3 board hooks + 4 legacy duplicate stubs documented) | Real A730 integration still held until owner lifts driver-edit hold |
| Phase 0 DT/ADT/UEFI_MEMDIAG handoff parity & `a730_zap.mbn` ELF fit (r3) | **HOST-COMPLETE** | Exact live-FDT gap (`0xACCFE000` not in ADT), `cmd-db`/`ZAP` parity, `gcd[12]` unmapped MMIO proven |
| Phase 2 SM8475 `cmd-db` host parser & ASan+UBSan HFI vote/BW oracle (r3) | **HOST-COMPLETE** | 4/4 bit-exact, 23/23 negative controls rejected; real 128 KiB capture pending Phase 2 hardware boot |
| `first_const_vma` & `__DATA` byte-for-byte attribution (r3) | **HOST-COMPLETE** | Exact per-object drivers identified; 1 page (`16,384 B`) `__DATA` policy slack left |
| Pinned macOS 27.3 (`26C5035r`) userspace ABI & build gate (r2) | **OPEN (BLOCKED ON LINUX HOST)** | Requires macOS 27 SDK/TBDs (`IOGPU.tbd`, frameworks), real `codesign`, Rust `+1.98.0` `arm64e-apple-darwin`, `glslangValidator`, patched Mesa/metal2vulkan (on `/media/disk_4` or macOS host); 2 `IOGPUMetalDeviceShim.h` signature mismatches + `resolveStub()` float/struct hazards remain open |
| A730/XNU driver edits & graphics hardware boots | **HELD (OWNER APPROVAL REQUIRED)** | Standing holds intact |
