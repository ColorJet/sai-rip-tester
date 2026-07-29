# SAI RIP Tester

GPU-accelerated RIP and colour-management evaluation tool for **ColorJet** digital
textile printing systems.

SAI RIP Tester lets an operator rip images through ColorJet's SAI engine and inspect
the result — colour separation, channel order, dot placement, and print output — for
any supported profile, without a full production setup.

## Download

Grab **`sai_update.exe`** from the [Releases](../../releases) page and run it.

- On a machine with nothing installed, it fetches and runs the full installer.
- On a machine that already has it, it updates in place — downloading only the parts
  that changed, so a routine update is a small download rather than the whole package.

That one small file is all you need; it handles both first install and every update.

## Updating

Run `sai_update.exe` again any time (or use the **Check for Updates** Start Menu
shortcut). It compares what you have against the latest release and pulls only the
differences.

## Requirements

- Windows 10 or 11, 64-bit
- NVIDIA GPU with a current driver (CUDA-capable)
- ~1 GB free disk for the full install

## Colour profiles

ICC profiles and print-scheme packs for ColorJet machines are available from the
ColorJet main website. This tool reads them directly, alongside common third-party
profile formats.

## Support

For access, licensing, or help, contact your ColorJet representative.

---

© 2026 ColorJet Group. The tester front-end source in this repository is
**source-available** — see [LICENSE](LICENSE.txt): you may read, run, and locally
modify it, but not redistribute it. The SAI RIP engine, SAI Studio, and the updater
binary are proprietary and distributed separately.
