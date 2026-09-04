# Scroll sandbox SBOM and verification

This is the small, runtime-specific inventory for the Scroll sandbox. The
repository-wide dependency inventory is the committed `uv.lock`; do not treat
this document as an alternate resolver or permit an unpinned installation.

| Component | Locked identity | License | Verification |
| --- | --- | --- | --- |
| uv | `0.12.9` x86_64 Linux archive | MIT/Apache-2.0 | SHA-256 `ec7a99cd05e0cd7f80243f135ce1361c76835cb0ee60055d14d20eba8eba1460` |
| CPython | `3.12.14+20260901` x86_64 Linux install-only archive | PSF-2.0 | SHA-256 `72748da13197c1fb161e3afeef20a6a385ff24f2165e6e2758e47008e7faba4c` |
| pydantic-monty | `0.0.21` | MIT | SHA-256 `7e84ef67b9e72f751819f6e7d4761eae3e3aa782d396f7777cd7948a05f4a5f7` |
| pydantic-monty-client | `0.0.21` cp312 manylinux x86_64 | MIT | SHA-256 `6272ec5f21aaabcbc23d9ebc57dc8c89c3903bcb4c2d9821d742fcc6b8449c1c` |
| pydantic-monty-runtime | `0.0.21` cp312 manylinux x86_64 | MIT | SHA-256 `31efcfa7e821a0420e2f34866df0767d2924b445e85c875c5f946d7f6adbe44c` |
| Monty worker | `.venv/bin/monty` | MIT | SHA-256 `bc4767743e5fb9fa360fbee21ded25e2642d8ad89a5c4f81b02a67d66c93a385` |
| Scroll source | `niceIrene/Scroll@313077708ea105cc79bf0a997338e14dae916f8c` | Apache-2.0 | vendored source and license in `vendor/scroll_context/` |

On the reference Linux host, bootstrap only with:

```bash
scripts/bootstrap_scroll_runtime.sh
scripts/run_tests.sh tests/plugins/test_scroll_stage0_monty.py
```

The tracked bootstrap script downloads the two archives into ignored
project-local paths, verifies the listed digests before extraction, and refuses
to replace an existing virtualenv based on another Python. It never installs a
global launcher. `locked_monty_available()` repeats the interpreter and package-version checks,
validates each installed wheel's locked `RECORD` digest and every recorded file,
and checks the worker digest immediately before a checkout is created. A
mismatch disables the plugin rather than selecting another interpreter. System
Python and global launchers are not changed.

To update this inventory, first update the plan's approved lock tuple, verify
the fetched artifacts before installation, regenerate `uv.lock`, update this
file and `UPSTREAM.md` if applicable, rerun Stage 0, and obtain a new
pre-evaluation review decision. Never update only this document.
