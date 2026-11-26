#!/usr/bin/env python3
from pathlib import Path
import importlib.util,json
H=Path(__file__).resolve().parent;R=H.parents[3]
s=importlib.util.spec_from_file_location('target_frames',H/'target-frames.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
T=R/'out/liuqin-r101-a3r1-work/evidence/timesync';pin=json.loads((T/'inputs.json').read_text())
for entry in pin['binary_slices']:
 live={'uuid':entry['UUID'].replace('-',''),'subtype':entry['cpu_subtype'],'base':'123400000','status':'ok'}
 image=m.MainImage(T/'clocksyncd',pin,live);assert image.slide==0x23400000;assert image.uuid==live['uuid'];assert image.contains_runtime(0x1234010c8);assert len(image.instruction(0x1000010c8))==1
try:m.MainImage(T/'clocksyncd',pin,{**live,'uuid':'0'*32})
except ValueError:pass
else:raise AssertionError('UUID mismatch accepted')
try:m.MainImage(T/'clocksyncd',{**pin,'extracted_files':{'clocksyncd':'0'*64}},live)
except ValueError:pass
else:raise AssertionError('SHA mismatch accepted')
# Mock only the independent checksum verifier here; test target section isolation.
rows=['LQ101 SNAPSHOT_BEGIN: target_s=60']
for name,tid,slide,base in [('WindowServer',1,'1000','100000000'),('clocksyncd',2,'2000','123400000')]:
 rows += [f'LQ102 TARGET_BEGIN: name={name} phase=waits pid={tid}', 'LQ101 USER_MAP: min=0 max=8000000000 machine_max=8000000000 va_bits=39 source=BCM2837-native-4k-TTBR0', f'LQ101 SHARED_REGION: slide={slide} uuid=abc',f'LQ101 WAIT: tid={tid}', f'LQ102 TARGET_END: name={name} phase=waits']
for name,tid,base in [('WindowServer',1,'100000000'),('clocksyncd',2,'123400000')]:
 rows += [f'LQ102 TARGET_BEGIN: name={name} phase=walk',f'LQ102 MAIN_IMAGE: base={base} subtype=80000002 uuid=abc status=ok',f'LQ101 WALK_VALIDATION: tid={tid} invalid_rc=14', f'LQ101 FRAME: tid={tid} depth=0 lr_raw=123456 fp_raw=654321', f'LQ102 TARGET_END: name={name} phase=walk']
rows += ['LQ101 SNAPSHOT_END: target_s=60']
m.coverage.snapshot_coverage=lambda lines:[{'target_s':60,'complete':True,'begin_line':1,'end_line':len(rows)}]
for name,tid,slide in [('WindowServer',1,0x1000),('clocksyncd',2,0x2000)]:
 record=m.export('\n'.join(rows).encode(),60,name);assert record['slide']==slide and [f['tid'] for f in record['frames']]==[tid] and record['invalid_address_read_failed']
bad=rows.copy();bad[1]='LQ102 TARGET_BEGIN: name=WindowServer phase=walk'
try:m.export('\n'.join(bad).encode(),60,'WindowServer')
except ValueError:pass
else:raise AssertionError('unbalanced target accepted')
print('PASS: both real pinned slices, UUID/SHA rejection, per-target isolation, phase integrity')
