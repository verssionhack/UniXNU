#!/usr/bin/env python3
import hashlib,importlib.util,struct,tempfile,unittest
from pathlib import Path
s=importlib.util.spec_from_file_location('frames',Path(__file__).with_name('validate-user-frames.py'));m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
class CacheFixture:
    uuid='a'*32
    def instruction(self,address):return [(0x94000000).to_bytes(4,'little')] if address==0x1000 else []
class FramesTests(unittest.TestCase):
    def record(self):return {'va_bits':39,'map_min':0,'map_max':1<<39,'slide':0x10000,'cache_uuid':'a'*32,'invalid_address_read_failed':True,'frames':[{'tid':1,'depth':0,'lr_raw':0xab00000000011004}]}
    def test_signed_lr_slide_callsite(self):
        r=m.validate(self.record(),[CacheFixture()]);self.assertTrue(r['callsite_validation_passed']);self.assertFalse(r['native_reader_validated']);self.assertEqual(r['frames'][0]['lr_raw'],0xab00000000011004)
    def test_wrong_uuid(self):
        r=self.record();r['cache_uuid']='b'*32
        with self.assertRaises(ValueError):m.validate(r,[CacheFixture()])
    def test_requires_invalid_read_failure(self):
        r=self.record();r['invalid_address_read_failed']=False;self.assertFalse(m.validate(r,[CacheFixture()])['callsite_validation_passed'])
    def test_noncache_frame_rejected(self):
        r=self.record();r['frames'][0]['lr_raw']=0x21004;self.assertFalse(m.validate(r,[CacheFixture()])['callsite_validation_passed'])
    def test_instructions(self):
        for word in [0x94000000,0xd63f0200]:self.assertTrue(m.is_call(word.to_bytes(4,'little'),0x1000))
        for word in [0x14000000,0xd61f0200,0xd65f03c0,0xd503201f]:self.assertIsNone(m.is_call(word.to_bytes(4,'little'),0x1000))
class CacheParsingTests(unittest.TestCase):
    def make(self,folder,prot=5):
        data=bytearray(260);data[:16]=b'dyld_v1  arm64e'.ljust(16,b'\0')
        struct.pack_into('<II',data,16,104,1);data[88:104]=bytes.fromhex('a'*32)
        struct.pack_into('<QQQII',data,104,0x1000,4,256,5,prot);struct.pack_into('<I',data,256,0x94000000)
        p=Path(folder)/'cache';p.write_bytes(data)
        return {'path':str(p),'uuid':'a'*32,'sha256':hashlib.sha256(data).hexdigest()}
    def test_real_parser_offset_and_permissions(self):
        with tempfile.TemporaryDirectory() as d:
            cache=m.Cache(self.make(d));self.assertEqual(cache.instruction(0x1000),[(0x94000000).to_bytes(4,'little')]);self.assertEqual(cache.instruction(0x1004),[])
            cache.data.close()
    def test_non_executable_mapping(self):
        with tempfile.TemporaryDirectory() as d:
            cache=m.Cache(self.make(d,1));self.assertEqual(cache.instruction(0x1000),[]);cache.data.close()
    def test_cache_hash_mismatch(self):
        with tempfile.TemporaryDirectory() as d:
            entry=self.make(d);entry['sha256']='0'*64
            with self.assertRaisesRegex(ValueError,'SHA mismatch'):m.Cache(entry)

class ExportTests(unittest.TestCase):
    def module(self):
        spec=importlib.util.spec_from_file_location('export',Path(__file__).with_name('frames-from-log.py'));module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
    def log(self,invalid_rc=14):
        rows=['LQ101 USER_MAP: min=0 max=8000000000 machine_max=8000000000 va_bits=39 source=BCM2837-native-4k-TTBR0',
              'LQ101 SHARED_REGION: base=1000 slide=10000 uuid='+('a'*32),
              f'LQ101 WALK_VALIDATION: tid=1 mode=raw-host-callsite-pending invalid_rc={invalid_rc} enabled=0',
              'LQ101 FRAME: tid=1 depth=0 fp_raw=20000 lr_raw=ab00000000011004 normalized=unknown']
        h=14695981039346656037
        for b in ('\n'.join(rows)+'\n').encode():h=((h^b)*1099511628211)&((1<<64)-1)
        return ('LQ101 SNAPSHOT_BEGIN: target_s=60\n'+'\n'.join(rows)+f'\nLQ101 SNAPSHOT_END: target_s=60 lines=4 hash={h:x} complete=1\n').encode()
    def test_verified_export_to_validator(self):
        record=self.module().export(self.log(),60);self.assertTrue(m.validate(record,[CacheFixture()])['callsite_validation_passed'])
    def test_truncated_export_refused(self):
        with self.assertRaises(ValueError):self.module().export(self.log().split(b'LQ101 SNAPSHOT_END:')[0],60)
    def test_invalid_read_evidence_not_invented(self):
        record=self.module().export(self.log(0),60);self.assertFalse(m.validate(record,[CacheFixture()])['callsite_validation_passed'])
if __name__=='__main__':unittest.main()
