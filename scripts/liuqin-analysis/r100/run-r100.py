#!/usr/bin/env python3
"""Run r100a validation boot on Liuqin with observer-driven abort guards (CPU, kAksUnsupported rate, respawn storm)."""
from pathlib import Path
import argparse
import datetime
import importlib.util
import json
import re
import time

D = Path(__file__).resolve().parent

FATAL = re.compile(rb'KERNEL PANIC|UNIXNU PANIC|panic\(cpu|PANICc\d|LIUQIN PANIC_DIAG:|PNB panic\(|LIUQIN UFS: ERR |LIUQIN USB: ERR ')
SI_RE = re.compile(rb'LIUQIN EXEC_TOP:[^\n]*\bsi=(\d+)')
TARGET_DENY_RE = re.compile(rb'LIUQIN DENY_EXEC: denied[^\n]*(?:coreaudiod|audiomxd)')
TASK_HDR_RE = re.compile(rb'^LIUQIN TASK_CPU_HDR: dt_ms=(\d+)(?:.*\bmax_pid=(\d+))?')
TASK_ROW_RE = re.compile(rb'^LIUQIN TASK_CPU: rank=\d+ comm=(\S+) win_ms=(\d+) wpct10=(\d+)(?:.*\bexits=(\d+))?')
AKS_WIN_RE = re.compile(rb'^LIUQIN AKS_DRV_WIN: dt_ms=(\d+) calls=(\d+) unsup=(\d+)')

ABORT_THRESHOLDS = {
    'cpu_pct_limit': 10.0,
    'cpu_consecutive_30s_windows': 2,
    'aks_unsup_per_sec_limit': 50.0,
    'aks_unsup_consecutive_windows': 2,
    'max_pid_grace_s': 150.0,
    'max_pid_window_s': 65.0,
    'max_pid_delta_limit': 45,
    'aks_sec_exits_30s_limit': 5,
}


class AbortMonitor:
    """Evaluate r98 abort guards over streamed USB serial chunks and elapsed timestamps."""

    def __init__(self, max_si: int, si_window: int) -> None:
        self.max_si = max_si
        self.si_window = si_window
        self.line_buf = b''
        self.tail = b''
        self.max_si_seen = 0
        self.si_samples: list[tuple[float, int]] = []
        self.target_deny_ts: list[float] = []
        self.max_pid_seen = 0
        self.max_pid_samples: list[tuple[float, int]] = []
        self.cur_hdr_dt_ms = 0
        self.win_cpu_hit: set[str] = set()
        self.cpu_streak = {'applekeystored': 0, 'securityd': 0}
        self.prev_exits = {'applekeystored': 0, 'securityd': 0}
        self.unsup_streak = 0
        self.abort_reason: str | None = None

    def _close_task_cpu_window(self) -> None:
        for name in self.cpu_streak:
            if name in self.win_cpu_hit:
                self.cpu_streak[name] += 1
            else:
                self.cpu_streak[name] = 0
        self.win_cpu_hit.clear()

    def feed_line(self, raw_ln: bytes, now_e: float) -> str | None:
        """Process one log line (without CR/LF) at elapsed time now_e seconds."""
        m_hdr = TASK_HDR_RE.match(raw_ln)
        if m_hdr:
            self._close_task_cpu_window()
            for name, st in self.cpu_streak.items():
                if st >= 2 and not self.abort_reason:
                    self.abort_reason = f'cpu guard triggered: {name} >10% CPU in 2 consecutive 30s windows at {now_e:.1f}s'
            self.cur_hdr_dt_ms = int(m_hdr.group(1))
            if m_hdr.group(2) is not None:
                mp = int(m_hdr.group(2))
                if mp > self.max_pid_seen:
                    self.max_pid_seen = mp
                if now_e > ABORT_THRESHOLDS['max_pid_grace_s']:
                    self.max_pid_samples = [
                        (ts, sv)
                        for ts, sv in self.max_pid_samples
                        if now_e - ts <= ABORT_THRESHOLDS['max_pid_window_s']
                    ]
                    self.max_pid_samples.append((now_e, self.max_pid_seen))
                    base_pid = self.max_pid_samples[0][1]
                    if not self.abort_reason and (self.max_pid_seen - base_pid) > ABORT_THRESHOLDS['max_pid_delta_limit']:
                        self.abort_reason = (
                            f'respawn guard triggered: max_pid delta={self.max_pid_seen - base_pid} '
                            f'(>45 in 65s after t=150s) at {now_e:.1f}s'
                        )
            return self.abort_reason

        m_row = TASK_ROW_RE.match(raw_ln)
        if m_row:
            cname = m_row.group(1).decode(errors='replace')
            win_ms = int(m_row.group(2))
            if cname in self.cpu_streak:
                if self.cur_hdr_dt_ms >= 15000 and (win_ms * 10 > self.cur_hdr_dt_ms):
                    self.win_cpu_hit.add(cname)
                    if not self.abort_reason and self.cpu_streak[cname] >= 1:
                        self.abort_reason = (
                            f'cpu guard triggered: {cname} >10% CPU in 2 consecutive 30s windows at {now_e:.1f}s'
                        )
                if m_row.group(4) is not None:
                    exits_now = int(m_row.group(4))
                    delta_ex = exits_now - self.prev_exits[cname]
                    self.prev_exits[cname] = exits_now
                    if self.cur_hdr_dt_ms >= 15000 and not self.abort_reason and delta_ex > ABORT_THRESHOLDS['aks_sec_exits_30s_limit']:
                        self.abort_reason = (
                            f'respawn guard triggered: {cname} exits delta={delta_ex} (>5 in 30s) at {now_e:.1f}s'
                        )
            return self.abort_reason

        m_aks = AKS_WIN_RE.match(raw_ln)
        if m_aks:
            adt_ms = int(m_aks.group(1))
            unsup = int(m_aks.group(3))
            if adt_ms >= 2000 and (unsup * 1000 > 50 * adt_ms):
                self.unsup_streak += 1
                if self.unsup_streak >= 2 and not self.abort_reason:
                    rate = (unsup * 1000.0) / adt_ms
                    self.abort_reason = f'aks unsupported guard triggered: {rate:.1f}/s (>50/s sustained) at {now_e:.1f}s'
            else:
                self.unsup_streak = 0
            return self.abort_reason

        return self.abort_reason

    def feed_chunk(self, data: bytes, now_e: float) -> str | None:
        """Process one captured USB byte chunk and return abort reason string if triggered."""
        self.tail = (self.tail + data)[-16384:]
        fresh = self.tail[max(0, len(self.tail) - len(data)):]
        self.line_buf += data
        while b'\n' in self.line_buf:
            raw_ln, self.line_buf = self.line_buf.split(b'\n', 1)
            self.feed_line(raw_ln.rstrip(b'\r'), now_e)
        for sm in SI_RE.finditer(self.tail):
            sv = int(sm.group(1))
            if sv > self.max_si_seen:
                self.max_si_seen = sv
                self.si_samples.append((now_e, sv))
        for _ in TARGET_DENY_RE.finditer(fresh):
            self.target_deny_ts.append(now_e)
        if self.max_si > 0 and not self.abort_reason:
            self.target_deny_ts = [t for t in self.target_deny_ts if now_e - t <= self.si_window]
            base_si = 0
            for ts, sv in self.si_samples:
                if now_e - ts <= self.si_window:
                    break
                base_si = sv
            if self.max_si_seen - base_si > self.max_si or len(self.target_deny_ts) > self.max_si:
                self.abort_reason = (
                    f'si guard triggered: max_si={self.max_si_seen} win_delta={self.max_si_seen - base_si} '
                    f'target_deny_win={len(self.target_deny_ts)} at {now_e:.1f}s'
                )
        return self.abort_reason


def main() -> None:
    """Boot candidate boot.img volatiles, stream USB logs, and enforce r98 abort guards."""
    spec = importlib.util.spec_from_file_location('common', D / 'device_runner.py')
    common = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(common)

    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--tag', default='r100a')
    p.add_argument('--follow', action='store_true')
    p.add_argument('--seconds', type=int, default=150)
    p.add_argument('--fatal-tail', type=int, default=35)
    p.add_argument('--max-si', type=int, default=20)
    p.add_argument('--si-window', type=int, default=120)
    a = p.parse_args()

    image = D / 'candidate' / 'boot.img'
    info = json.loads((D / 'candidate' / 'boot.json').read_text())
    if common.sha(image) != info['image_sha256']:
        raise RuntimeError('Image hash mismatch')
    validation = json.loads((D / 'validation-summary-r100a.json').read_text())
    if validation['status'] != 'PASS' or validation['experiment'] != 'r100a':
        raise RuntimeError('r100a validation failed')
    if common.sha(image) != validation['boot_sha256']:
        raise RuntimeError('r100a validated boot image hash mismatch')
    if common.sha(D / 'kernel.macho') != validation['kernel_sha256']:
        raise RuntimeError('r100a validated kernel hash mismatch')

    folder = D / f"boot-{a.tag}-{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}"
    folder.mkdir()
    print('Evidence:', folder, flush=True)

    if not common.fastboot_present():
        print('Dropping running device to fastboot via LIQDBG001...', flush=True)
        common.bootloader(folder)

    record = {
        'tag': a.tag,
        'start': datetime.datetime.now().astimezone().isoformat(),
        'image_sha256': common.sha(image),
        'boot_method': 'fastboot boot (volatile, not flashed)',
        'max_si_limit': a.max_si,
        'si_window': a.si_window,
        'r98_abort_thresholds': ABORT_THRESHOLDS,
    }
    s = None
    start = time.monotonic()
    status = start
    total = 0
    reg_done = tc_denies = deny_hits = el0_traps = gen_faults = 0
    scratch_err = rehash_ok = rehash_err = sc_tasks = kmsgs = ui_kmsgs = aks_calls = 0
    aks_drv_events = cs4k_misses = enospc_hits = vnode_lines = jetsam_tops = lscan_dirs = 0
    mon = AbortMonitor(max_si=a.max_si, si_window=a.si_window)
    fatal_at = None

    try:
        reply = common.command(['fastboot', '-s', common.SERIAL, 'boot', str(image)], timeout=60)
        (folder / 'fastboot.log').write_text(reply.stdout + reply.stderr)
        with (folder / 'usb.log').open('ab', buffering=0) as log:
            while time.monotonic() - start < a.seconds or a.follow or (fatal_at and time.monotonic() - fatal_at < a.fatal_tail):
                if s is None:
                    try:
                        s = common.open_debug()
                    except (common.serial.SerialException, OSError):
                        s = None
                    if s:
                        s.dtr = True
                        s.rts = True
                        s.write(b'replay\n')
                        s.flush()
                if s:
                    try:
                        data = s.read(8192)
                        if data:
                            log.write(data)
                            total += len(data)
                            now_e = time.monotonic() - start
                            reg_done += data.count(b'LIUQIN FILE: phase=end')
                            tc_denies += data.count(b'not in the trustcache')
                            deny_hits += data.count(b'LIUQIN DENY_EXEC: denied')
                            el0_traps += data.count(b'LIUQIN EL0 TRAP:')
                            gen_faults += data.count(b'LIUQIN EL0_FAULT:')
                            scratch_err += data.count(b'LIUQIN SCRATCH IO: error=')
                            rehash_ok += data.count(b'LIUQIN PAGE_REHASH:')
                            rehash_err += data.count(b'LIUQIN PAGE_REHASH_MISMATCH:')
                            sc_tasks += data.count(b'LIUQIN SC_TASK:')
                            kmsgs += data.count(b'LIUQIN KMSG:')
                            ui_kmsgs += data.count(b'LIUQIN UI_KMSG:')
                            aks_calls += data.count(b'LIUQIN AKS_CALL:')
                            aks_drv_events += data.count(b'LIUQIN AKS_DRV:')
                            cs4k_misses += data.count(b'LIUQIN CS4K_MISS:')
                            enospc_hits += data.count(b'LIUQIN ENOSPC:')
                            vnode_lines += data.count(b'LIUQIN VNODES:')
                            jetsam_tops += data.count(b'LIUQIN JETSAM_TOP:')
                            lscan_dirs += data.count(b'LIUQIN LSCAN_DIR:')

                            abort_reason = mon.feed_chunk(data, now_e)
                            if abort_reason:
                                print('ABORT:', abort_reason, flush=True)
                                break
                            if fatal_at is None and FATAL.search(mon.tail):
                                fatal_at = time.monotonic()
                                record['fatal'] = FATAL.search(mon.tail).group().decode(errors='replace')
                                print(f'Fatal observation; capturing {a.fatal_tail}s tail:', record['fatal'], flush=True)
                    except (common.serial.SerialException, OSError):
                        s.close()
                        s = None
                else:
                    time.sleep(0.25)
                now = time.monotonic()
                if fatal_at and not a.follow and now - fatal_at >= a.fatal_tail:
                    break
                if now - status >= 15:
                    print(
                        f'elapsed {int(now - start)}s captured {total}B reg={reg_done} '
                        f'tc={tc_denies} si={mon.max_si_seen} max_pid={mon.max_pid_seen} aks_drv={aks_drv_events} '
                        f'sc={sc_tasks} ui_kmsg={ui_kmsgs} aks={aks_calls}',
                        flush=True,
                    )
                    status = now
    except KeyboardInterrupt:
        record['interrupted'] = True
    finally:
        if s:
            s.close()
        record.update(
            end=datetime.datetime.now().astimezone().isoformat(),
            captured_bytes=total,
            reg_done=reg_done,
            tc_denies=tc_denies,
            deny_hits=deny_hits,
            max_si=mon.max_si_seen,
            max_pid=mon.max_pid_seen,
            el0_traps=el0_traps,
            gen_faults=gen_faults,
            scratch_err=scratch_err,
            rehash_ok=rehash_ok,
            rehash_err=rehash_err,
            sc_tasks=sc_tasks,
            kmsgs=kmsgs,
            ui_kmsgs=ui_kmsgs,
            aks_calls=aks_calls,
            aks_drv_events=aks_drv_events,
            cs4k_misses=cs4k_misses,
            enospc_hits=enospc_hits,
            vnode_lines=vnode_lines,
            jetsam_tops=jetsam_tops,
            lscan_dirs=lscan_dirs,
            abort_reason=mon.abort_reason,
            elapsed_seconds=int(time.monotonic() - start),
        )
        (folder / 'boot-record.json').write_text(json.dumps(record, indent=2) + '\n')
        print(json.dumps(record, indent=2))
        if mon.abort_reason:
            raise SystemExit(2)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        raise SystemExit('r100 stopped: ' + str(exc))
