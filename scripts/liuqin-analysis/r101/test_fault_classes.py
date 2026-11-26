#!/usr/bin/env python3
"""Existing process names must not hide new observed fault signatures."""
from pathlib import Path
import importlib.util,unittest
spec=importlib.util.spec_from_file_location('analysis',Path(__file__).with_name('analyze.py'));a=importlib.util.module_from_spec(spec);spec.loader.exec_module(a)
class FaultTests(unittest.TestCase):
    def row(self,**changes):return {'comm':'ReportCrashServ','stage':'exc_crash','exc':10,'sig':5,'code':'0x9000000',**changes}
    def test_new_signature_in_existing_process(self):
        r=a.fault_classes([self.row(stage='ux_sig',exc=2,sig=4,code='0x1')],[self.row()])[0]
        self.assertEqual(r['classification'],'new-signature-in-compared-capture');self.assertFalse(r['global_new_or_absent_claim'])
    def test_existing_signature_with_different_address(self):
        r=a.fault_classes([self.row(pc='0x1234')],[self.row(pc='0x9876')])[0]
        self.assertEqual(r['classification'],'pre-existing-unresolved')
    def test_parkd_expected_only_for_known_policy_signature(self):
        r=a.fault_classes([self.row(comm='parkd'),self.row(comm='parkd',sig=4)],[])
        self.assertEqual(r[0]['classification'],'expected-existing-denial-policy');self.assertNotEqual(r[1]['classification'],'expected-existing-denial-policy')
    def test_digit_only_native_hex_has_explicit_radix(self):
        row=a.observation_fields('LQ101 WAIT: t_ms=25 state=1 event=0 waitq=12345678 receive=10004001 hint=2')
        self.assertEqual(row['receive'],'0x10004001');self.assertEqual(row['waitq'],'0x12345678');self.assertEqual(row['hint'],2)
    def test_map_geometry_and_uuid_keep_their_radix(self):
        row=a.observation_fields('LQ101 USER_MAP: min=100000000 max=8000000000 va_bits=39')
        self.assertEqual(int(row['max'],16),1<<39)
        row=a.observation_fields('LQ101 SHARED_REGION: base=180000000 slide=100000 uuid=12345678901234567890123456789012')
        self.assertEqual(row['base'],'0x180000000');self.assertIsInstance(row['uuid'],str)
if __name__=='__main__':unittest.main()
