#!/usr/bin/env python3
"""Reproduce r100a panic-size evidence; verify USB/tail independence in pinned sources."""
from pathlib import Path
import hashlib,json
R=Path(__file__).resolve().parents[3];W=R/'out/liuqin-r101-work'
p=R/'out/liuqin-r100-work/evidence/boot-r100a-20261120-155217/usb.log';raw=p.read_bytes()
reason=b'userspace panic: boot task failure: mount-phase-1 - exited due to SIGABRT'
start=raw.index(b'PANICc5 '+reason);end=raw.rindex(reason)+len(reason)
f=W/'frozen-r100b-source';debug=(f/'bsd/dev/liuqin_debug.c').read_text();printf=(f/'osfmk/kern/printf.c').read_text();kern=(f/'osfmk/kern/debug.c').read_text()
stream=debug[debug.index('static char lq_pnb_buf'):debug.index('void liuqin_log_line(const char *fmt')]
assert 'lq_panic_tail' not in stream and 'liuqin_usb_force_note' in stream
assert 'liuqin_panic_usb_putc((unsigned char)c)' in printf
assert 'liuqin_panic_usb_flush();' in kern and 'liuqin_panic_capture(' in kern
screen=debug[debug.index('void\nliuqin_panic_screen(void)'):debug.index('static char lq_pnb_buf')]
assert 'sizeof(lq_panic_tail)' in screen
report={'log':str(p.relative_to(R)),'log_sha256':hashlib.sha256(raw).hexdigest(),
 'marker_offset':start,'last_reason_end_offset':end,'marker_through_last_reason_bytes':end-start,
 'marker_through_last_reason_fits_8KiB':end-start<=8192,
 'marker_line_bytes':len(raw[start:].splitlines(keepends=True)[0]),
 'usb_path':['osfmk/kern/printf.c: consdebug_putc_unbuffered -> liuqin_panic_usb_putc',
 'bsd/dev/liuqin_debug.c: lq_pnb_buf[192] -> liuqin_usb_force_note; flush before panic_screen'],
 'framebuffer_tail_bytes':8192,'usb_independent_of_framebuffer_tail':True,
 'limit':'A framebuffer tail can evict early panic text. Independent USB path is best effort; no guarantee against arbitrary USB loss.',
 'source_sha256':{str(x.relative_to(f)):hashlib.sha256(x.read_bytes()).hexdigest() for x in [f/'bsd/dev/liuqin_debug.c',f/'osfmk/kern/printf.c',f/'osfmk/kern/debug.c']}}
(W/'evidence/panic-path-review.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
