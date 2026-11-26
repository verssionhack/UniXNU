#!/usr/bin/env python3
"""A2 snapshot integrity, per-window conservation and unchanged guard decisions."""
from pathlib import Path
import hashlib,importlib.util,json,unittest
H=Path(__file__).resolve().parent;R=H.parents[3]
def load(name,path):
 s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
coverage=load('coverage_a2',H/'coverage.py');blocks=load('blocks',H/'block-coverage.py');runner=load('a2runner',H/'run-a2.py');undefined=load('undefined',H/'undefined-coverage.py');analysis=load('a2_analysis',H/'analyze-a2.py')
class A2Tests(unittest.TestCase):
 def snapshot(self):
  body=['LQ101 WAIT: tid=1','LQ102 THREAD_TAG: tid=1 tag=1 main=1'];checksum=14695981039346656037
  for b in ('\n'.join(body)+'\n').encode():checksum=((checksum^b)*1099511628211)&((1<<64)-1)
  return ['LQ101 SNAPSHOT_BEGIN: target_s=60',*body,f'LQ101 SNAPSHOT_END: target_s=60 lines=2 hash={checksum:x} complete=1']
 def test_includes_new_observer_prefix_in_checksum(self):self.assertTrue(coverage.snapshot_coverage(self.snapshot())[0]['complete'])
 def test_lost_new_prefix_line_detected(self):self.assertFalse(coverage.snapshot_coverage([l for l in self.snapshot() if not l.startswith('LQ102')])[0]['complete'])
 def window(self):return ['LQ102 BLK_WINDOW: t_ms=1000 bytes=300 writes=2 named=2 overflow_bytes=0 overflow_writes=0 legacy_bytes=200 legacy_writes=1','LQ102 BLK_WRITER: t_ms=1000 pid=1 comm=same bytes=100 writes=1 legacy_bytes=0 legacy_writes=0','LQ102 BLK_WRITER: t_ms=1000 pid=2 comm=same bytes=200 writes=1 legacy_bytes=200 legacy_writes=1']
 def test_block_conservation_and_legacy_bucket(self):
  w=blocks.block_windows(self.window())[0];self.assertTrue(w['complete']);self.assertTrue(w['legacy_breakdown_complete'])
 def test_missing_writer_line_detected(self):self.assertFalse(blocks.block_windows(self.window()[:-1])[0]['complete'])
 def test_orphan_writer_detected(self):self.assertFalse(blocks.block_windows(self.window()[1:])[0]['complete'])
 def test_legacy_mismatch_detected(self):
  w=blocks.block_windows([l.replace('legacy_bytes=200 legacy_writes=1','legacy_bytes=100 legacy_writes=1') if l.startswith('LQ102 BLK_WRITER:') else l for l in self.window()])[0]
  self.assertTrue(w['complete']);self.assertFalse(w['legacy_breakdown_complete'])
 def histories(self):
  def snap(target,body):
   checksum=14695981039346656037
   for b in ('\n'.join(body)+'\n').encode():checksum=((checksum^b)*1099511628211)&((1<<64)-1)
   return [f'LQ101 SNAPSHOT_BEGIN: target_s={target}',*body,f'LQ101 SNAPSHOT_END: target_s={target} lines={len(body)} hash={checksum:x} complete=1']
  return snap(60,['LQ102 HISTORY: kind=open n=1 rev=2 reuse_s=0','LQ101 EVENT: scope=last50-open seq=1'])+snap(120,['LQ102 HISTORY: kind=open n=1 rev=2 reuse_s=60'])
 def test_history_reference_requires_verified_original(self):
  records=coverage.history_references(self.histories());self.assertEqual(len(records),2);self.assertTrue(all(r['complete'] for r in records))
 def test_missing_original_history_is_failure(self):
  rows=[r for r in self.histories() if not r.startswith('LQ101 EVENT:')]
  self.assertTrue(all(not r['complete'] for r in coverage.history_references(rows)))
 def word_windows(self):return ['LQ102 UNDEFINED_TOTAL: t_ms=1000 events=100 overflow=0','LQ102 UNDEFINED: t_ms=1000 comm=ReportCrash word=d503205f total=100 delta=100','LQ102 UNDEFINED_TOTAL: t_ms=2000 events=101 overflow=0','LQ102 UNDEFINED: t_ms=2000 comm=ReportCrash word=d503205f total=101 delta=1']
 def test_word_counter_not_limited_by_detail_cap(self):self.assertTrue(all(w['complete'] for w in undefined.undefined_windows(self.word_windows())))
 def test_lost_word_row_detected(self):self.assertFalse(undefined.undefined_windows(self.word_windows()[:-1])[-1]['complete'])
 def test_actual_A1_is_incomplete_for_A2_not_absence(self):
  report=analysis.analyze(R/'out/liuqin-r101-work/evidence/a/boot-A1-20261120-175501')
  self.assertEqual(report['status'],'A2-observer-contract-incomplete');self.assertTrue(report['a2_contract']['snapshot_complete']);self.assertFalse(report['a2_contract']['undefined_counter_present']);self.assertFalse(report['no_lookup_claim_permitted'])
 def test_actual_A1_guard_calls_replay_identically(self):
  folder=R/'out/liuqin-r101-work/evidence/a/boot-A1-20261120-175501';raw=(folder/'usb.log').read_bytes();monitor=runner.Monitor();calls=0
  for row in (folder/'guard-trace.jsonl').read_text().splitlines():
   event=json.loads(row)
   if event['event']!='monitor':continue
   data=raw[event['offset']:event['offset']+event['length']]
   self.assertEqual(hashlib.sha256(data).hexdigest(),event['chunk_sha256']);self.assertEqual(monitor.step(event['elapsed'],data),event['result']);calls+=1
  self.assertEqual(calls,2130)
if __name__=='__main__':unittest.main()
