#!/usr/bin/env python3
"""Unmodified r101 layout/actual-fileset gates precede packaging. Never boots."""
from pathlib import Path
R=Path(__file__).resolve().parents[4];p=R/'scripts/liuqin-analysis/r101/package.py';s=p.read_text();old="W=R/'out/liuqin-r101-work'";assert s.count(old)==1
s=s.replace(old,"W=R/'out/liuqin-r101-a7-work'")
exec(compile(s,str(p),'exec'),{'__file__':str(p),'__name__':'__main__'})
