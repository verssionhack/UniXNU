#!/usr/bin/env python3
"""Target-scoped exports and UUID-selected Mach-O relocation; no guessed slides."""
from pathlib import Path
import hashlib,importlib.util,json,re,struct
H=Path(__file__).resolve().parent;R=H.parents[3]
def load(name,path):
 s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
coverage=load('a4_coverage',H.parent/'a2/coverage.py')
def fields(s):return dict(re.findall(r'(\w+)=([^ ]+)',s))
def export(raw,target,name):
 lines=raw.decode('utf8',errors='strict').splitlines();snaps=[s for s in coverage.snapshot_coverage(lines) if s['target_s']==target]
 if len(snaps)!=1 or not snaps[0]['complete']:raise ValueError('require unique complete checked snapshot')
 snap=snaps[0];selected=[];current=None;phases=[]
 for line in lines[snap['begin_line']:snap['end_line']-1]:
  if line.startswith('LQ102 TARGET_BEGIN:'):
   if current is not None:raise ValueError('nested targets')
   current=fields(line);phases.append(current) if current['name']==name else None
  elif line.startswith('LQ102 TARGET_END:'):
   if current is None or any(fields(line)[k]!=current[k] for k in ['name','phase']):raise ValueError('unbalanced target')
   current=None
  elif current and current['name']==name:selected.append(line)
 if current or [p['phase'] for p in phases]!=['waits','walk']:raise ValueError('missing target phase')
 def rows(prefix):return [fields(l) for l in selected if l.startswith(prefix)]
 maps=rows('LQ101 USER_MAP:');shared=rows('LQ101 SHARED_REGION:');images=rows('LQ102 MAIN_IMAGE:')
 if len(maps)!=1 or len(shared)!=1 or len(images)!=1:raise ValueError('target geometry/identity missing')
 va=maps[0];sr=shared[0];image=images[0]
 if va['source']!='BCM2837-native-4k-TTBR0' or int(va['machine_max'],16)!=1<<int(va['va_bits']):raise ValueError('VA geometry unqualified')
 fs=rows('LQ101 FRAME:');valid={int(f['tid']):int(f['invalid_rc']) for f in rows('LQ101 WALK_VALIDATION:')}
 return {'target_s':target,'name':name,'log_sha256':hashlib.sha256(raw).hexdigest(),'pid':int(phases[0].get('pid',0)), 'va_bits':int(va['va_bits']),'map_min':int(va['min'],16),'map_max':int(va['max'],16),'slide':int(sr['slide'],16),'cache_uuid':sr['uuid'],'main_image':image,'invalid_address_read_failed':bool(fs) and all(valid.get(int(f['tid']),0)!=0 for f in fs),'frames':[{'tid':int(f['tid']),'depth':int(f['depth']),'lr_raw':int(f['lr_raw'],16),'fp_raw':int(f['fp_raw'],16)} for f in fs], 'waits':rows('LQ101 WAIT:'),'regs':rows('LQ101 USER_STATE:'),'reads':rows('LQ101 WALK_READS:')}

def slices(data):
 if data[:4]==b'\xca\xfe\xba\xbe':
  n=struct.unpack_from('>I',data,4)[0]
  if n>32:raise ValueError('fat count')
  for i in range(n):
   cpu,sub,off,size,align=struct.unpack_from('>IIIII',data,8+20*i)
   if off+size>len(data):raise ValueError('fat bounds')
   yield data[off:off+size]
 elif data[:4]==b'\xcf\xfa\xed\xfe':yield data
 else:raise ValueError('unsupported Mach-O container')
class MainImage:
 def __init__(self,path,pin,live):
  data=Path(path).read_bytes()
  if hashlib.sha256(data).hexdigest()!=pin['extracted_files']['clocksyncd']:raise ValueError('binary SHA mismatch')
  candidates=[]
  for image in slices(data):
   magic,cpu,sub,kind,n,size=struct.unpack_from('<6I',image)
   if cpu!=0x100000c:continue
   if magic!=0xfeedfacf or cpu!=0x100000c or kind!=2 or n>128 or 32+size>len(image):raise ValueError('Mach-O header')
   cursor=32;uuid=None;segments=[];text=None
   for i in range(n):
    cmd,sz=struct.unpack_from('<II',image,cursor)
    if sz<8 or cursor+sz>32+size:raise ValueError('Mach-O command')
    if cmd==0x1b:uuid=image[cursor+8:cursor+24].hex()
    if cmd==0x19:
     name=image[cursor+8:cursor+24].rstrip(b'\0');base,vmsize,off,filesize,maxprot,prot=struct.unpack_from('<QQQQII',image,cursor+24)
     if name==b'__TEXT':text=base
     if off+filesize>len(image):raise ValueError('segment bounds')
     segments.append((base,filesize,off,prot))
    cursor+=sz
   if uuid==live['uuid'] and sub==int(live['subtype'],16):candidates.append((image,sub,uuid,segments,text))
  if live['status']!='ok' or len(candidates)!=1:raise ValueError('live UUID/subtype not uniquely matched')
  image,sub,uuid,self.segments,text=candidates[0];self.data=image;self.uuid=uuid
  spec=next((s for s in pin['binary_slices'] if s['UUID'].replace('-','')==uuid and int(s['cpu_subtype'],16)==sub),None)
  if not spec or hashlib.sha256(image).hexdigest()!=spec['slice_sha256'] or text is None:raise ValueError('slice identity mismatch')
  self.slide=int(live['base'],16)-text;self.text=text
 def instruction(self,address):
  return [self.data[o+address-b:o+address-b+4] for b,size,o,prot in self.segments if prot&4 and b<=address and address+4<=b+size]
 def contains_runtime(self,address):
  return any(b<=address-self.slide<b+size and prot&4 for b,size,_,prot in self.segments)
