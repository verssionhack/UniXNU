#!/usr/bin/env python3
"""Package only A5's isolated image using the unchanged A/r100b configuration."""
from pathlib import Path
R=Path(__file__).resolve().parents[4]
p=R/'scripts/liuqin-analysis/r101/package.py';source=p.read_text()
old="W=R/'out/liuqin-r101-work'";assert source.count(old)==1
source=source.replace(old,"W=R/'out/liuqin-r101-a5-work'")
source=source.replace('Raw candidate mode selected; frames untrusted pending host validation','A5 raw candidate mode selected; frames untrusted pending host validation')
exec(compile(source,str(p),'exec'),{'__file__':str(p),'__name__':'__main__'})
