# Changelog

Customer-facing release notes for SAI RIP Tester.

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
