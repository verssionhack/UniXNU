#!/usr/bin/env python3
from pathlib import Path
import copy,importlib.util
H=Path(__file__).resolve().parent;s=importlib.util.spec_from_file_location('decode',H/'decode-state.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
B=0x100000000;S=0x1000
record={'target_s':60,'pid':150,'main_image':{'status':'ok','uuid':m.MAIN_UUID,'subtype':'80000002','base':hex(B)},'slide':S,'cache_uuid':m.CACHE_UUID,'map_min':0x1000,'map_max':1<<39}
def fixture(cm=1,cp=0,gm=0,gp=1):
 rows=[]
 def put(key,addr,a=0,b=0):rows.append({'key':key,'addr':hex(addr),'rc':'0','a':hex(a),'b':hex(b)})
 put('DAEMON',B+0x6e0a0,0x10000);put('DAEMON_END',B+0x6e0a0,0x10000)
 put('D0',0x10000,B+0x6d6e8);put('D1',0x10008);put('D1_END',0x10008)
 put('ISAM',S+0x180447ba8,0x7ffffffffff8,1);put('ISAV',S+0x180447bb8,1)
 put('IVAR0',S+0x2728f5438,0x1000000008,0x2000000018);put('IVAR1',S+0x2728f5448,0x3000000028)
 put('ARRIV',S+0x1eb1deb78,16<<32);put('SETIV',S+0x1eb1dee90,16<<32)
 for prefix,key,addr,p,setp,arrp,matched,pending,singleton in [('CN','CLKY',0x6e1a0,0x20000,0x40000,0x50000,cm,cp,0x60000),('GN','GPTY',0x6e180,0x30000,0x70000,0x80000,gm,gp,0)]:
  put(key,B+addr,p,singleton);put(key+'_END',B+addr,p,singleton)
  put(prefix+'0',p,B+0x6ce28,0x11110);put(prefix+'1',p+16,0x22220,setp);put(prefix+'2',p+32,0x33330,arrp);put(prefix+'3',p+40,arrp,0x44440)
  put(prefix+'S0',setp,S+0x1ed9533f8);put(prefix+'S1',setp+16,0,matched<<32)
  put(prefix+'A0',arrp,S+0x1ed954668);put(prefix+'A1',arrp+16);put(prefix+'A2',arrp+32,pending<<32)
 return rows
begin=[{'version':'6','main':hex(B),'shared_slide':hex(S),'invalid_rc':'14'}]
def decode(rows,rec=None):return m.decode(rec or record,begin,[{'status':'recorded','requests':str(len(rows))}],rows)
def modify(rows,key,**kw):next(r for r in rows if r['key']==key).update(kw)
assert decode(fixture())['outcome']=='gptp_pending'
assert decode(fixture(0,1,0,0))['outcome']=='clock_pending'
r=fixture();modify(r,'DAEMON',a='0');modify(r,'DAEMON_END',a='0');assert decode(r)['outcome']=='nil_daemon'
r=fixture();modify(r,'DAEMON',rc='14',a='0');assert decode(r)['outcome']=='unknown'
r=fixture();modify(r,'D1',b='90000');modify(r,'D1_END',b='90000');r += [{'key':'SV0','addr':'90000','rc':'0','a':hex(B+0x6d648),'b':'a0000'},{'key':'SV1','addr':'90010','rc':'0','a':'b0000','b':'c0000'}];assert decode(r)['outcome']=='created_resumed_server_init'
r=fixture();modify(r,'GNA0',a='12345');assert decode(r)['outcome']=='unknown'
r=fixture();modify(r,'CLKY_END',a='0');assert decode(r)['outcome']=='unknown'
assert decode(fixture(0,1,0,1))['outcome']=='unknown'
r=fixture();r.append(copy.deepcopy(r[0]));assert decode(r)['outcome']=='unknown'
r=copy.deepcopy(record);r['main_image']['uuid']='0'*32;assert decode(fixture(),r)['outcome']=='unknown'
r=fixture();modify(r,'D0',a='12345');assert decode(r)['outcome']=='unknown'
r=fixture();modify(r,'CLKY',addr=hex(S+0x275739818));assert decode(r)['outcome']=='unknown'
print('PASS: 12 state outcome/identity/read-failure/class/race/ambiguity tests')
