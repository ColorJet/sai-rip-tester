# Changelog

Customer-facing release notes for SAI RIP Tester.

## 1.3.1 — 2026-11-14

Fix release. No new colour or halftone behaviour.

- **Solid ink printed as blank.** Fixed a packing fault in 2-bit output that could
  leave fully covered areas empty on the printer.
- **Ink limit enforced.** The profile's total-ink limit is now applied, not only
  reported. A new tester option (`--enforce-ink-limit`) controls it, with an
  override percentage.
- **Post-linearisation applied.** The profile's linearisation curve is now used
  during output; `--no-pl-lut` in the tester turns it off for comparison prints.
- **Drop volumes.** Real head drop volumes can be entered when a profile only states
  nominal values.
- **Driver check at startup.** The tester now logs the GPU, driver and CUDA version
  and warns when the NVIDIA driver is older than the engine needs (CUDA 13, driver
  580 or newer). This was the cause of every "GPU allocation error" reported so far.
- **Visible updates.** The in-app update writes an install log to `%TEMP%` and
  tells you where it is.
- **Test checklist.** A fill-in test form ships in `docs\TEST_CHECKLIST.md`
  (Start menu: Test Checklist).

## 1.3.0 — 2026-07-29

Print-quality release.

- **Smoother gradients.** Reworked halftoning removes the stepping that could appear
  in graduated tones; gradients now transition cleanly.
- **More accurate tone.** Ink levels now follow each profile's own calibration more
  closely, so mid-tones and quarter-tones print truer to target.
- **Textile-aware screening.** A clustered-dot dithering option lays down ink that
  holds better on absorbent fabric, alongside the standard dispersed dithering for
  smooth work.
- **Sharper scaling.** Image upscaling retains more fine detail, and is faster.
- **Cleaner edges.** An optional mode keeps vibrant colours crisp where two designs
  meet, instead of blending them.
- **4-colour (CMYK) support.** In addition to 6- and 8-channel machines, standard
  CMYK printers are now supported through their own profiles.
- **Broader profile support.** Reads ColorJet profiles plus common third-party
  formats.
- **Small updates.** The new standalone updater installs on a fresh machine and, on
  an existing one, downloads only the components that changed.

Colour output for existing profiles is unchanged by default; the new behaviours are
opt-in until selected.

## 1.2.1 — 2026-07-26

- Colour-accuracy fixes for extended-ink (Blue / Red / Orange / Green) profiles.
- Automatic channel-order handling from the print scheme.
- In-place self-update.
