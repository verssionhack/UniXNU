# r101 A5 — bounded clocksyncd state observation

A5 adds raw state reads to A4's observer pipeline while retaining **A3r1 behavior** (nTWE=1, nTWI unchanged, 512 MiB Data). A4's original exit5, raw log, framing recovery and source/analysis manifests are immutable. No transport/parser repair or behavior fix is bundled.

[Host layout and semantics audit](liuqin-r101-a5-host-audit.md) preceded coding. It verifies daemon/server fields, notifier matched-set and callback-array fields, exact count implementations, class objects and live ISA/layout qualification. Raw host audit files are frozen under `out/liuqin-r101-a5-work/evidence/host-audit/`.

Only `liuqin_r101_walk.inc` and `liuqin_r101_waits.inc` differ from A4. The existing main-image UUID reader now returns an identity qualification: subtype `0x80000002` and clocksyncd UUID `91f59f6a64c3321c88b00cc7a485ab1c`. Only clocksyncd's slot uses that return value to enter the new helper. A second gate compares the task's own shared-cache UUID to `8b1e17c672d6301791a4916022e3612e`. Main fields use own base; framework/CoreFoundation/runtime fields use this task's own shared slide. WindowServer walking and all previous hook/transport/sampling logic remain unchanged.

State reads occur **after the existing fail-closed USB completion fence**, in the final target-read phase at 60/120/300 s. A generic helper records `key/address/rc/two raw words`; a fixed chain reads daemon, notifier/singleton/queue globals, layout cells and bounded daemon/server/notifier/collection prefixes. Requests are capped at 64 / 1024 B (fixed worst case 38 / 608 B), plus one separately reported invalid-address probe. Native attempts/unavailable include that known EFAULT probe; host per-record rc values distinguish real unavailable reads. Object fields are not interpreted by the kernel. Strong pointers are range/alignment checked unchanged. No target methods, writes, page-ins, pointer-authentication operations or task suspension occur.

Daemon fields and main/framework globals are reread for changes. Other scalar/count reads remain racy; no atomic object snapshot is claimed. Unknown collection subclasses, identity/layout mismatches, failed reads and conflicting states remain explicit null evidence. The helper neither traverses callback contents nor identifies individual block owners. Callback counts concern this process's notifier, with those limits.

The host reports four explicit outcomes, using the audited conditions: nil daemon; clock availability pending; gPTP availability pending (with clock match/singleton evidence); stored server whose initializer returned after listener resume invocation. A nonnil server does not establish a successful XPC request/reply or current active listener. Missing reads never become zero/nil. Empty pending arrays do not prove registration or callback completion.

## Host verification and run criteria

Build/package/source gates pass. TEXT `0x1cc000`, DATA `0x27c000`, TEXT_EXEC `0x9a4000`; const VMA `0xfffffff0070062e0`, **2528 B above `...5900` gate**. Boot/kernel identities are in validation-summary and host-verification. Existing 999-byte arguments, ADT, trust, device files, nTWE instruction, USB bookkeeping/fence and early sampler match A4 exactly.

Tests: 10 exact native main-header/identity cases; 5 actual C state-reader cases (read cap, invalid probe, cache identity, unavailable reads, unmasked noncanonical pointer rejection); 11 host state-decode cases covering the four outcomes, read failures, mismatched classes/identities, races and ambiguous states; 6 inherited assessment cases; exact A4 guard replay (2203 calls). Prior accepted manifests are checked unchanged.

One authorized volatile boot: 120 s fastboot cooldown, 480 s capture, unchanged abort guards, automatic return to verified fastboot. No separate go is required under the user's current authorization. No flashing, key/signing, network, dummy TimeSync service, display or Data-size change.

Predeclared success: inherited observer/target contracts, all three checksum-verified snapshots, bounded balanced state sections, qualified identities/probe, and explicit four-way or unknown state classification. Failed/unavailable reads can be a complete observer null result; they cannot establish a readiness state. Scientific success requires qualified fields supporting a unique state, ideally repeated across all three snapshots. Native-reader validation remains false independently of plausible frames/state.

Keep the original line-anchored raw capture assessment. If TRAP/observer concatenation recurs, preserve exit5 and raw data; any exact suffix recovery is a separate supplemental analysis. Do not weaken checksum verification or silently normalize the capture verdict.

The 512 KiB total, 448 KiB detail, 96 KiB reservation per snapshot and 253 B record limit remain. New evidence is bounded to at most 38 word records plus state markers per snapshot; verify actual totals and loss counters after capture. Data-fill/memory/SCTLR/WFE are context checks, not extra behavior variables. **EL0 TRAP=0 does not mean zero faults.**
