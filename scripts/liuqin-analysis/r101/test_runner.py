#!/usr/bin/env python3
"""Meaningful host checks of abort decisions, artifact refusal and exact trace replay."""
from pathlib import Path
import hashlib,importlib.util,json,tempfile,unittest
H=Path(__file__).resolve().parent
def load(name,path):
    s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
runner=load('runner',H/'run-r101.py');replay=load('replay',H/'replay-exact.py')
LINE=b'fs_tx_enter_internal:1: disk1s1 launchd: ENOSPC: test\n'
class RunnerTests(unittest.TestCase):
    def test_partial_serial_line_and_empty_ticks(self):
        m=runner.Monitor();m.step(1,LINE[:20]);m.step(2,LINE[20:]);m.step(10)
        self.assertEqual(m.enospc.windows[0]['count'],1)
        self.assertIsNone(m.summary()['abort_reason'])
    def test_fatal_across_chunks(self):
        m=runner.Monitor();m.step(1,b'PA');self.assertIsNone(m.fatal)
        m.step(2,b'NICc5 userspace panic\n');self.assertEqual(m.fatal,'PANICc5')
    def test_cpu_guard_retained(self):
        m=runner.Monitor()
        hdr=b'LIUQIN TASK_CPU_HDR: dt_ms=30000 max_pid=200\n'
        row=b'LIUQIN TASK_CPU: rank=0 comm=securityd win_ms=4000 wpct10=1 exits=0\n'
        m.step(30,hdr+row);m.step(60,hdr+row)
        self.assertIn('cpu guard',m.summary()['abort_reason'])
    def test_monotonic_clock(self):
        m=runner.Monitor();m.step(2)
        with self.assertRaises(ValueError):m.step(1)
    def trial(self,folder):
        raw=bytearray();events=[];m=runner.Monitor()
        for now,data in [(0,b''),(1,LINE*161),(10,b''),(11,LINE*161),(20,b'')]:
            off=len(raw);raw.extend(data);result=m.step(now,data)
            events.append({'event':'monitor','elapsed':now,'offset':off,'length':len(data),'chunk_sha256':hashlib.sha256(data).hexdigest(),'result':result})
        self.assertIn('ENOSPC',m.summary()['abort_reason'])
        events.append({'event':'capture_end','bytes':len(raw),'result':m.summary()})
        trace=''.join(json.dumps(e)+'\n' for e in events).encode();(folder/'usb.log').write_bytes(raw);(folder/'guard-trace.jsonl').write_bytes(trace)
        (folder/'boot-record.json').write_text(json.dumps({'log_sha256':hashlib.sha256(raw).hexdigest(),'trace_sha256':hashlib.sha256(trace).hexdigest(),'source_sha256':{}}))
    def test_exact_abort_replay_including_empty_ticks(self):
        with tempfile.TemporaryDirectory() as d:
            f=Path(d);self.trial(f);r=replay.replay(f)
            self.assertEqual(r['timing'],'exact-recorded-calls');self.assertEqual(r['steps'],5)
            self.assertIn('ENOSPC',r['result']['abort_reason'])
    def test_modified_raw_trace_refused(self):
        with tempfile.TemporaryDirectory() as d:
            f=Path(d);self.trial(f);(f/'usb.log').write_bytes(b'corruption')
            with self.assertRaisesRegex(ValueError,'USB log hash'):replay.replay(f)
    def test_unrecorded_offset_hole_refused(self):
        with tempfile.TemporaryDirectory() as d:
            f=Path(d);self.trial(f);events=[json.loads(x) for x in (f/'guard-trace.jsonl').read_text().splitlines()];events[1]['offset']=1
            trace=''.join(json.dumps(x)+'\n' for x in events).encode();(f/'guard-trace.jsonl').write_bytes(trace)
            r=json.loads((f/'boot-record.json').read_text());r['trace_sha256']=hashlib.sha256(trace).hexdigest();(f/'boot-record.json').write_text(json.dumps(r))
            with self.assertRaisesRegex(ValueError,'Non-contiguous'):replay.replay(f)
    def test_missing_observers_are_failure_not_absence(self):
        analysis=load('analysis',H/'analyze.py')
        with tempfile.TemporaryDirectory(dir=runner.R/'out/liuqin-r101-work') as d:
            f=Path(d);self.trial(f);result=analysis.analyze(f)
            self.assertEqual(result['status'],'boot-or-observer-contract-failed')
            self.assertFalse(result['no_lookup_claim_permitted'])
            self.assertEqual(result['missing_snapshot_targets'],[60,120,300])
    def test_wrong_image_hash_refused(self):
        old=runner.R
        with tempfile.TemporaryDirectory() as d:
            try:
                runner.R=Path(d);e=runner.R/'out/liuqin-r101-work/evidence/a';e.mkdir(parents=True)
                (e/'boot.img').write_bytes(b'changed image');(e/'kernel.macho').write_bytes(b'kernel')
                (e/'validation-summary.json').write_text(json.dumps({'status':'PASS','variant':'a','boot_sha256':'0'*64,'kernel_sha256':'0'*64}))
                with self.assertRaisesRegex(RuntimeError,'hash mismatch'):runner.validate('a')
            finally:runner.R=old
if __name__=='__main__':unittest.main()
