#!/usr/bin/env python3
"""Exercise the actual grow script with stand-ins for macOS disk utilities."""
from pathlib import Path
import os
import subprocess
import tempfile

HERE=Path(__file__).resolve().parent
with tempfile.TemporaryDirectory(prefix='liuqin-grow-test-') as tmp:
    root=Path(tmp)
    marker=root/'grown'
    calls=root/'calls'
    utility=root/'diskutil'
    utility.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$CALLS"\nif [ "$1" = apfs ] && [ "${FAIL_GROW:-0}" = 1 ]; then exit 1; fi\n')
    buddy=root/'PlistBuddy'
    buddy.write_text('#!/bin/sh\nprintf "%s\\n" "$CONTAINER"\n')
    utility.chmod(0o755);buddy.chmod(0o755)
    code=(HERE/'grow-data.sh').read_text().replace('/private/var/db/.liuqin-data-grown',str(marker))
    code=code.replace('/private/var/tmp',str(root)).replace('/usr/sbin/diskutil',str(utility)).replace('/usr/libexec/PlistBuddy',str(buddy))
    script=root/'grow.sh';script.write_text(code)
    env=dict(os.environ,CALLS=str(calls),CONTAINER='disk2')
    def run(**values):
        return subprocess.run(['/bin/sh',str(script)],env=dict(env,**values),capture_output=True).returncode
    assert run(FAIL_GROW='1')!=0 and not marker.exists()
    assert run()==0 and marker.exists()
    before=calls.read_bytes()
    assert run()==0 and calls.read_bytes()==before
    marker.unlink()
    for invalid in ('disk','disk2;echo unsafe','disk2s1','rdisk2','disk../../tmp'):
        before=calls.read_text().count('apfs')
        assert run(CONTAINER=invalid)!=0 and not marker.exists()
        assert calls.read_text().count('apfs')==before
    print('PASS: APFS grow retries, completion marker, rerun suppression and strict container-name validation')
