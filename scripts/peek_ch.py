#!/usr/bin/env python3
from pathlib import Path
import re
import sys

path = Path(sys.argv[1])
t = path.read_text(encoding="utf-8")
print(t[:2000])
print("==== STREETS ====")
for m in re.finditer(
    r"(?:улиц[аеуы]\s+|авеню\s+|роуд\s+|шоссе\s+)[«\"]?[А-ЯЁA-Z0-9][А-Яа-яёA-Za-z0-9\-\s]{1,40}",
    t,
):
    print("ST:", m.group(0)[:90])
