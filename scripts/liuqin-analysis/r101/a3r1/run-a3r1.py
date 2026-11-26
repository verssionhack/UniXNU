#!/usr/bin/env python3
"""Volatile, timestamped A3r1 observer capture. Invoke only after the separate per-boot go."""
from pathlib import Path
import argparse,datetime,hashlib,importlib.util,json,subprocess,time
R=Path(__file__).resolve().parents[4]
def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
base=module('r100',R/'scripts/liuqin-analysis/r100/run-r100.py')
policy=module('r101_guards',Path(__file__).resolve().parent.parent/'guards.py')
common=module('device',R/'out/liuqin-r100-work/evidence/device_runner.py')
def sha(p):
    with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
class Monitor:
    def __init__(self):
        self.old=base.AbortMonitor(20,120);self.enospc=policy.EnospcPrintGuard();self.buf=b'';self.last=0.0;self.fatal=None
    def step(self,now,data=b''):
        if now<self.last:raise ValueError('Non-monotonic guard event')
        self.last=now;self.enospc.tick(now)
        if data:
            self.old.feed_chunk(data,now);self.buf+=data
            while b'\n' in self.buf:
                line,self.buf=self.buf.split(b'\n',1);self.enospc.feed_line(line.rstrip(b'\r'),now)
            if len(self.buf)>1048576:raise RuntimeError('Unterminated serial line exceeds 1 MiB')
            match=base.FATAL.search(self.old.tail)
            if match and not self.fatal:self.fatal=match[0].decode(errors='replace')
        return self.summary()
    def summary(self):
        return {'abort_reason':self.old.abort_reason or self.enospc.abort_reason,'fatal':self.fatal,'max_si':self.old.max_si_seen,'max_pid':self.old.max_pid_seen}

def validate(variant):
    d=R/f'out/liuqin-r101-a3r1-work/evidence/{variant}';report=json.loads((d/'validation-summary.json').read_text())
    if report['status']!='PASS' or report['variant']!=variant:raise RuntimeError('Variant validation failed')
    if sha(d/'boot.img')!=report['boot_sha256'] or sha(d/'kernel.macho')!=report['kernel_sha256']:raise RuntimeError('Validated artifact hash mismatch')
    frozen=R/'out/liuqin-r101-a3r1-work/evidence/analysis-rule.json'
    rule=json.loads(frozen.read_text())
    if sha(Path(__file__).resolve().parent.parent/'analyze.py')!=rule['sha256'] or sha(frozen.with_name('analysis-rule-frozen.py.txt'))!=rule['sha256']:
        raise RuntimeError('A3r1 fault rule changed after freeze; no boot')
    if not report.get('walker_candidates') or report['kernel_args_len']!=999:raise RuntimeError('A3r1 observer mode/config mismatch; no boot')
    return d,report

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--variant',choices=['a','b'],default='a');p.add_argument('--tag',default='A3r1');p.add_argument('--seconds',type=int,default=480);p.add_argument('--ambient-celsius',type=float);p.add_argument('--check',action='store_true');a=p.parse_args()
    if not 400<=a.seconds<=600:p.error('Capture duration must be 400–600 s')
    d,validation=validate(a.variant)
    if a.check:print(json.dumps({'status':'PASS','variant':a.variant,'boot_sha256':validation['boot_sha256'],'device_action':False}));return
    if not common.fastboot_present():raise SystemExit('Expected be7ca114 in fastboot; no automatic pre-run reset')
    folder=d/(f'boot-{a.tag}-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'));folder.mkdir()
    print('Evidence:',folder,flush=True)
    monitor=Monitor();offset=0;process=None;serial=None;replayed=False;fatal_at=None;failure=None;reset_ok=False;start_ns=None
    record={'variant':a.variant,'tag':a.tag,'start':datetime.datetime.now().astimezone().isoformat(),'image_sha256':validation['boot_sha256'],'kernel_sha256':validation['kernel_sha256'],'boot_method':'fastboot boot (volatile, not flashed)','cooldown_seconds':120,'ambient_celsius':a.ambient_celsius,'temperature':{'available':False,'reason':'No qualified readable sensor configured'},'guards':{'original':base.ABORT_THRESHOLDS,'enospc_print':policy.ENOSPC_POLICY},'source_sha256':{str(x.relative_to(R)):sha(x) for x in [Path(__file__),Path(__file__).resolve().parent.parent/'guards.py',R/'scripts/liuqin-analysis/r100/run-r100.py',R/'out/liuqin-r100-work/evidence/device_runner.py']}}
    with (folder/'guard-trace.jsonl').open('x',buffering=1) as trace,(folder/'usb.log').open('xb',buffering=0) as log:
        def event(kind,**kw):trace.write(json.dumps({'event':kind,'mono_ns':time.monotonic_ns(),**kw},separators=(',',':'))+'\n')
        try:
            event('cooldown_start');cold_start=time.monotonic()
            while time.monotonic()-cold_start<120:
                if not common.fastboot_present():raise RuntimeError('Fastboot disappeared during cooldown')
                time.sleep(min(5,max(0,120-(time.monotonic()-cold_start))))
            record['cooldown_actual_seconds']=time.monotonic()-cold_start;event('cooldown_end')
            start_ns=time.monotonic_ns();event('capture_start',start_ns=start_ns)
            # Popen permits serial polling while the image is transferring; do not
            # block capture waiting for fastboot's completed transfer/boot response.
            process=subprocess.Popen(['fastboot','-s',common.SERIAL,'boot',str(d/'boot.img')],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            event('fastboot_start',pid=process.pid);status_at=time.monotonic()
            while True:
                now=(time.monotonic_ns()-start_ns)/1e9
                if process.poll() is not None and process.returncode!=0:raise RuntimeError(f'fastboot boot failed ({process.returncode})')
                if process.poll() is None and now>60:raise RuntimeError('Fastboot boot command exceeded 60 s')
                if serial is None:
                    try:serial=common.open_debug()
                    except (common.serial.SerialException,OSError) as exc:event('serial_open_error',detail=str(exc))
                    if serial:
                        serial.dtr=True;serial.rts=True;event('serial_open')
                        if not replayed:serial.write(b'replay\n');serial.flush();replayed=True;event('initial_replay')
                data=b''
                if serial:
                    try:data=serial.read(8192)
                    except (common.serial.SerialException,OSError) as exc:
                        event('serial_disconnect',detail=str(exc));serial.close();serial=None
                else:time.sleep(.1)
                # This elapsed value is the actual argument supplied to guards.
                now=(time.monotonic_ns()-start_ns)/1e9
                if data:log.write(data)
                state=monitor.step(now,data)
                event('monitor',elapsed=now,offset=offset,length=len(data),chunk_sha256=hashlib.sha256(data).hexdigest(),result=state)
                offset+=len(data)
                if state['abort_reason']:break
                if state['fatal'] and fatal_at is None:fatal_at=now;event('fatal_tail_start',elapsed=now)
                if fatal_at is not None and now-fatal_at>=35:break
                if now>=a.seconds and fatal_at is None:break
                if time.monotonic()-status_at>=15:
                    print(f'elapsed={now:.1f}s bytes={offset} max_pid={state["max_pid"]}',flush=True);status_at=time.monotonic()
        except (Exception,KeyboardInterrupt) as exc:
            failure=f'{type(exc).__name__}: {exc}';event('capture_exception',detail=failure)
        finally:
            if serial:serial.close()
            if process:
                if process.poll() is None:process.kill()
                stdout,stderr=process.communicate();(folder/'fastboot.log').write_bytes(stdout+stderr);record['fastboot_exit']=process.returncode
            record.update(monitor.summary(),captured_bytes=offset,capture_error=failure,end=datetime.datetime.now().astimezone().isoformat(),elapsed_seconds=(time.monotonic_ns()-start_ns)/1e9 if start_ns else 0)
            event('capture_end',result=monitor.summary(),bytes=offset)
            # A complete trial includes verified return to fastboot. Never flash.
            try:common.bootloader(folder);reset_ok=common.fastboot_present();event('fastboot_verified',ok=reset_ok)
            except Exception as exc:record['return_error']=str(exc);event('return_failed',detail=str(exc))
            record['returned_to_fastboot']=reset_ok
    record['log_sha256']=sha(folder/'usb.log');record['trace_sha256']=sha(folder/'guard-trace.jsonl')
    (folder/'boot-record.json').write_text(json.dumps(record,indent=2)+'\n')
    assessment_exit=5
    try:
        acceptance=module('a2r1_assessment',Path(__file__).resolve().parent.parent/'a2r1/assessment.py').assess(folder)
        assessment_exit=acceptance['exit_code'];record['capture_status']=acceptance['status']
        (folder/'capture-assessment.json').write_text(json.dumps(acceptance,indent=2)+'\n')
    except Exception as exc:
        record['capture_status']='assessment-failed-incomplete';record['assessment_error']=str(exc)
    record['assessment_exit_code']=assessment_exit
    (folder/'boot-record.json').write_text(json.dumps(record,indent=2)+'\n');print(json.dumps(record,indent=2))
    if failure or not reset_ok:raise SystemExit(1)
    if monitor.summary()['abort_reason']:raise SystemExit(2)
    if monitor.fatal:raise SystemExit(3)
    if assessment_exit:raise SystemExit(assessment_exit)
if __name__=='__main__':main()
