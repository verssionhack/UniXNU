#!/usr/bin/env python3
import importlib.util,unittest
from pathlib import Path
s=importlib.util.spec_from_file_location('checks',Path(__file__).with_name('coverage.py'));c=importlib.util.module_from_spec(s);s.loader.exec_module(c)
class CoverageTests(unittest.TestCase):
    def fixture(self):
        row='LQ101 WAIT: tid=4';h=14695981039346656037
        for b in (row+'\n').encode():h=((h^b)*1099511628211)&((1<<64)-1)
        return ['LQ101 SNAPSHOT_BEGIN: target_s=60',row,f'LQ101 SNAPSHOT_END: target_s=60 lines=1 hash={h:x} complete=1']
    def test_complete(self):self.assertTrue(c.snapshot_coverage(self.fixture())[0]['complete'])
    def test_deleted_or_duplicated_line(self):
        f=self.fixture()
        for rows in [f[:1]+f[2:],f[:2]+f[1:]]:self.assertFalse(c.snapshot_coverage(rows)[0]['complete'])
    def test_unclosed(self):self.assertFalse(c.snapshot_coverage(self.fixture()[:-1])[0]['complete'])
    def test_emitter_suppression(self):self.assertFalse(c.snapshot_coverage([x.replace('complete=1','complete=0') for x in self.fixture()])[0]['complete'])
    def test_cpu_interleave(self):
        f=self.fixture();f.insert(1,'LQ101 CPU_TIME: ticks=8');self.assertTrue(c.snapshot_coverage(f)[0]['complete'])
    def test_duplicate_snapshot_target(self):
        self.assertTrue(all(not r['complete'] for r in c.snapshot_coverage(self.fixture()*2)))
    def test_malformed_markers_are_failures(self):
        for rows in [['LQ101 SNAPSHOT_BEGIN: garbage'],self.fixture()[:-1]+['LQ101 SNAPSHOT_END: target_s=60'],['LQ101 SNAPSHOT_END: target_s=60 lines=0 hash=0 complete=1']]:
            self.assertFalse(c.snapshot_coverage(rows)[0]['complete'])
    def test_prints_never_invent_matches(self):
        r=c.apfs_coverage(['fs_tx_enter_internal:1: disk1s1 launchd: ENOSPC: test','LQ101 EVENT: pid=1 err=28'])
        self.assertEqual(r['apfs_enospc_print_lines_not_matched_to_syscall_event'],1);self.assertFalse(r['unmatched_is_async_claim'])
if __name__=='__main__':unittest.main()
