#!/usr/bin/env python3
"""Export A2 raw frames only after both LQ101 and LQ102 snapshot evidence verifies."""
from pathlib import Path
import importlib.util
H=Path(__file__).resolve().parent
def load(name,path):
 s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
coverage=load('a2_coverage',H/'coverage.py');export=load('export',H.parent/'frames-from-log.py');export.checks=coverage
if __name__=='__main__':export.main()
