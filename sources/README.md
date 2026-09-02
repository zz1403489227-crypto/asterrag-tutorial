# Frozen source checkouts

The tutorial is aligned to AsterRAG commit
`98894c2c42c015a3c874c6b3c986ac863c85b731`, but the complete source checkout is
not vendored into this tutorial repository.

To run the source-anchor audit locally, place the frozen checkout at
`sources/AsterRAG` or set up an equivalent read-only checkout before running:

```bash
git clone https://github.com/zz1403489227-crypto/AsterRAG.git sources/AsterRAG
git -C sources/AsterRAG checkout --detach 98894c2c42c015a3c874c6b3c986ac863c85b731
python3 scripts/audit-tutorial.py
```

The upstream and teaching-reference SHAs are recorded in
`../evidence/SOURCES.lock.md`.

