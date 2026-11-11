# Example programs

Small CheriBSD programs to try the model on each CPU. Each is prebuilt in
`bin/` as purecap (`-purecap`) and plain RV64 (`-plain`), static and
stripped.

| Program | What it shows |
|---|---|
| `hello` | the ABI and the capability of a stack buffer |
| `bounds` | a write one byte past a 16-byte heap buffer: purecap stops it with `SIGPROT`, plain RV64 does not notice |
| `list` | pointer chasing through a 16,384-node linked list: purecap nodes are twice as large |

`bin/se/ptrchase` and `bin/se/matmul` are freestanding RV64 programs
(from `../baseline/bench.c`) for SE mode, which needs no CheriBSD.

* `run.sh CPU [BINARY ...]` boots CheriBSD and runs the binaries on `CPU`
  (`atomic`, `timing`, `minor` or `o3`).
* `build.sh` rebuilds `bin/` from `src/` with the CHERI SDK.

The top-level [README](../../../README.md) explains the setup and the output.
