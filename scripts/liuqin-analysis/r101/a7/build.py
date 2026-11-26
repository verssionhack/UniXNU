#!/usr/bin/env python3
"""Build/freeze A7 only. No boot; layout gates checked separately before acceptance."""
from pathlib import Path
R=Path(__file__).resolve().parents[4]
p=R/'scripts/liuqin-analysis/r101/build.py';s=p.read_text();old="W=R/'out/liuqin-r101-work'";assert s.count(old)==1
s=s.replace(old,"W=R/'out/liuqin-r101-a7-work'")
exec(compile(s,str(p),'exec'),{'__file__':str(p),'__name__':'__main__'})
