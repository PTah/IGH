#!/usr/bin/env python3
import re, sys
from pathlib import Path
path, pat, n = Path(sys.argv[1]), sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 2
t = path.read_text(encoding="utf-8")
for i, m in enumerate(re.finditer(pat, t, re.I)):
    if i >= n:
        break
    a, b = max(0, m.start() - 100), min(len(t), m.end() + 180)
    print("---")
    print(t[a:b].replace("\n", " "))
