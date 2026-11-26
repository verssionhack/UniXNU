#!/usr/bin/env python3
"""Use the established builder with A5r1's isolated staging/evidence directory."""
from pathlib import Path
R=Path(__file__).resolve().parents[4]
p=R/'scripts/liuqin-analysis/r101/build.py';source=p.read_text()
old="W=R/'out/liuqin-r101-work'";assert source.count(old)==1
source=source.replace(old,"W=R/'out/liuqin-r101-a5r1-work'")
exec(compile(source,str(p),'exec'),{'__file__':str(p),'__name__':'__main__'})
