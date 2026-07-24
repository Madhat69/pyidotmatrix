#!/usr/bin/env python3
"""Compatibility shim: the parser now lives in the package.

It ships as `pyidotmatrix/btsnoop.py` and as the `pyidotmatrix-btsnoop`
console script. This file stays so existing invocations
(`python tools/parse_btsnoop.py capture.log`) and any notes citing that path
keep working.
"""

from pyidotmatrix.btsnoop import main

if __name__ == "__main__":
    raise SystemExit(main())
