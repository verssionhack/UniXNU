#!/usr/bin/env python3
"""Build Liuqin board input and qualify IOHIDDevice slots against 26C5035r."""
from pathlib import Path
import hashlib
import importlib.util
import json
import os
import shutil
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3] if 'liuqin-analysis' in str(__file__) else Path('/home/kurumin/Codes/Github/UniXNU')
SOURCES = Path('/media/disk_4/unixnu_workspace/liuqin-input-sources')
HID = SOURCES / 'IOHIDFamily'
NVT = SOURCES / 'ShengNovatekTouch'
SDK = Path('/media/disk_4/unixnu_workspace/macos27-cross/sdk/MacOSX26.1.sdk')
FW = Path('/media/disk_4/xiaomi_pad_pro6_linux_workspace/xiaomipad-6pro-mainline/device/firmware/usr/lib/firmware/novatek/liuqin/novatek_nt36532_m81_fw_csot.bin')

def require(ok, message):
    if not ok:
        raise RuntimeError(message)

def sha(path):
    return hashlib.file_digest(path.open('rb'), 'sha256').hexdigest()

def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result

def main():
    tree=Path.cwd()
    dev=Path(os.environ['UNIXNU_DEVICE'])
    src=dev/'drivers/LiuqinInput'
    out=tree/'build/liuqin-input'
    out.mkdir(parents=True, exist_ok=True)
    for path, revision in ((HID,'e31e90a24c27ad6cbe981650d12a1a4124065b03'),(NVT,'4d6133c374c4980a1fa82879ad25b5ef2ae47896')):
        require(subprocess.check_output(['git','-C',str(path),'rev-parse','HEAD'],text=True).strip()==revision, str(path)+': source pin')
        require(not subprocess.check_output(['git','-C',str(path),'status','--porcelain'],text=True).strip(),str(path)+': clean source')
    include=out/'include'
    for source, relative in ((HID/'IOHIDFamily','IOKit/hid'),(HID/'IOHIDSystem/IOKit/hidsystem','IOKit/hidsystem')):
        target=include/relative
        target.mkdir(parents=True,exist_ok=True)
        for path in source.glob('*.h'):
            shutil.copy2(path,target/path.name)
    shutil.copy2(SDK/'usr/include/TargetConditionals.h',include/'TargetConditionals.h')
    builder=module('lq_gpu_builder',ROOT/'scripts/liuqin-analysis/r102-gpu/build-liuqin-adreno730.py')
    ethernet=module('lq_object_info',dev/'scripts/build-identity-ethernet.py')
    objroot=tree/'build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837'
    cpp=json.loads((objroot/'iokit/DEVELOPMENT/IOPlatformExpert.cpo.json').read_text().strip().rstrip(','))
    c=json.loads((objroot/'bsd/DEVELOPMENT/bsd_init.o.json').read_text().strip().rstrip(','))
    flags=['-I',str(include),'-I',str(src),'-I',str(NVT),'-I',str(ROOT/'drivers/QcomGeniSpi'),
           '-I',str(tree/'.cache/xnu-work/osfmk'),'-idirafter',str(SDK/'System/Library/Frameworks/Kernel.framework/Versions/A/Headers'),
           '-Wall','-Wextra','-Werror','-Wno-unused-parameter','-Wno-deprecated-declarations',
           '-Wno-unused-variable','-Wno-unnecessary-virtual-specifier','-Wno-overriding-option',
           '-Wno-deprecated-enum-enum-conversion','-Wno-deprecated-anon-enum-enum-conversion',
           '-Wno-c99-designator','-Wno-reorder-init-list','-Wno-missing-designated-field-initializers']
    def compile(path, name=None):
        recipe=c if path.suffix=='.c' else cpp
        dst=out/(name or (path.stem+'.o'))
        command=builder.make_cmd(recipe,path,dst,[])
        # These source HID headers must precede any kernel-exported compatibility headers.
        command[1:1]=flags
        p=subprocess.run(command,cwd=recipe['directory'],text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
        (out/(path.stem+'.log')).write_text(p.stdout)
        require(p.returncode==0,p.stdout[-9000:])
        return dst
    objects=[compile(src/name) for name in ('LiuqinKeyboard.cpp','LiuqinTouch.cpp','LiuqinBacklight.cpp','LiuqinButtons.cpp','GeniI2c.c','Wn8030.c')]
    objects += [compile(ROOT/'drivers/QcomGeniSpi/GeniSpi.c'),compile(NVT/'NvtProtocol.c')]
    cover=compile(src/'KeyboardCover.cpp')
    abi=json.loads((src/'hid-device-26C5035r.json').read_text())
    kc=Path('/media/disk_4/unixnu_workspace/ramdisk_dir/unixnu/ipsw/26C5035r/kernelcache.decompressed')
    require(sha(kc)==abi['kernelcache_sha256'],'pinned kernelcache identity')
    slots=[(int(t,16),int(d,16)) for t,d in abi['slots']]
    slide=int(abi['collection_slide'],16)
    bindings={n:int(v,16)+slide for n,v in abi['bindings'].items()}
    symbols,reloc=ethernet.object_info(cover.read_bytes())
    reserved='__ZN15OSMetaClassBase25_RESERVEDOSMetaClassBase3Ev'
    dispatch='__ZN15OSMetaClassBase8DispatchE5IORPC'
    vtables=('__ZTV18ShengKeyboardCover','__ZTVN18ShengKeyboardCover9MetaClassE')
    projected={va for va,(name,_) in reloc.items() if name==reserved}
    expected={next(a for n,a,_ in symbols if n==name)+16+16*8 for name in vtables}
    require(projected==expected,'exact class/metaclass inherited Dispatch projections')
    require(all((reloc[a][1]>>32)&65535==slots[16][1] for a in projected),'Dispatch PAC diversity')
    subprocess.run(['llvm-objcopy','--redefine-sym',reserved+'='+dispatch,str(cover)],check=True)
    symbols,reloc=ethernet.object_info(cover.read_bytes())
    sys.path.insert(0,str(ROOT/'kits/XnuPrelink'))
    from kc_image import Image
    native_bytes=kc.read_bytes()
    fileset=Image(native_bytes)
    native_names=Image(native_bytes,fileset.entries['com.apple.kernel'][1]).symbols()
    require(dispatch in native_names.get(slots[16][0],[]),'native Dispatch slot identity')
    vt=next(a for n,a,_ in symbols if n=='__ZTV18ShengKeyboardCover')+16
    entries=[reloc.get(vt+8*i) for i in range(len(slots))]
    require(all(entries),'full IOHIDDevice vtable')
    pure=int(abi['pure_target'],16)
    # Inherited family calls are resolved by their slot, preserving the PAC
    # diversity from the public declaration. Qualified start/stop/free calls
    # use the corresponding override slot in this same table.
    override_slots={}
    for i,(name,word) in enumerate(entries):
        require(word>>63 and (word>>48)&1 and (word>>49)&3==0 and (word>>32)&65535==slots[i][1],f'slot {i}: authenticated-pointer ABI')
        if '18ShengKeyboardCover' in name:
            prefix='__ZNK18ShengKeyboardCover' if name.startswith('__ZNK') else '__ZN18ShengKeyboardCover'
            override_slots[name[len(prefix):]]=i
        else:
            require(slots[i][0]!=pure,f'pure slot {i} implemented')
            if '11IOHIDDevice' in name:
                require(bindings.setdefault(name,slots[i][0]+slide)==slots[i][0]+slide,f'slot {i}: inherited target')
            else:
                require(i<abi['base_slots'] and name in native_names.get(slots[i][0],[]),f'slot {i}: inherited IOService identity ({name})')
    for name,_,kind in symbols:
        if kind!=1 or '11IOHIDDevice' not in name or name in bindings:
            continue
        prefix='__ZNK11IOHIDDevice' if name.startswith('__ZNK') else '__ZN11IOHIDDevice'
        suffix=name[len(prefix):]
        require(suffix in override_slots,f'unresolved family call {name}')
        bindings[name]=slots[override_slots[suffix]][0]+slide
    text='.text\n.p2align 2\n'
    addresses=''
    used={n for n,_,k in symbols if k==1 and '11IOHIDDevice' in n}
    for name in sorted(used):
        va=bindings[name]
        if name.endswith('gMetaClassE') or name.startswith('__ZTV'):
            addresses+=f'.globl {name}\n.set {name}, {va:#x}\n'
        else:
            addresses+=f'.globl {name}.original\n.set {name}.original, {va:#x}\n'
            text+=f'.globl {name}\n{name}:\n bti c\n b {name}.original\n'
    for stem,data in (('hid-bindings',text),('hid-addresses',addresses)):
        asm=out/(stem+'.S');asm.write_text(data)
        obj=out/(stem+'.o')
        subprocess.run([cpp['arguments'][0],'-target','arm64e-apple-ios27.0','-c',str(asm),'-o',str(obj)],check=True)
        objects.append(obj)
    late=out/'KeyboardCover.late.o'
    subprocess.run(['llvm-objcopy','--remove-section=__DATA,__mod_init_func','--globalize-symbol=__GLOBAL__sub_I_KeyboardCover.cpp',str(cover),str(late)],check=True)
    objects.append(late)
    asm=out/'touch-firmware.S'
    asm.write_text('.section __BOOTDATA,__data\n.p2align 4\n.globl _liuqin_touch_firmware\n_liuqin_touch_firmware:\n.incbin '+json.dumps(str(FW))+'\nLtouch_end:\n.p2align 3\n.globl _liuqin_touch_firmware_size\n_liuqin_touch_firmware_size:\n.quad Ltouch_end-_liuqin_touch_firmware\n')
    fw_obj=out/'touch-firmware.o'
    subprocess.run([cpp['arguments'][0],'-target','arm64e-apple-ios27.0','-c',str(asm),'-o',str(fw_obj)],check=True)
    objects.append(fw_obj)
    archive=out/'libLiuqinInput.a'
    archive.unlink(missing_ok=True)
    subprocess.run(['llvm-ar','rcsD',str(archive),*[str(p) for p in objects]],check=True)
    report={'status':'PASS','hardware_validation':False,'slots':len(slots),'archive_sha256':sha(archive),
            'firmware':str(FW),'firmware_sha256':sha(FW),'sources':{str(p):sha(p) for p in src.iterdir() if p.is_file()},
            'hid_bindings':{n:hex(bindings[n]) for n in sorted(used)}}
    (out/'build-report.json').write_text(json.dumps(report,indent=2)+'\n')
    print('Liuqin input: IOHIDDevice ABI PASS,',len(slots),'slots;',len(objects),'objects')

if __name__=='__main__':
    main()
