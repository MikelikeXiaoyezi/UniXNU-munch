# munch XNU patch set

`patches-munch/` is the first munch kernel patch set. It is derived from
[aTechGeekDev/ios-apollo](https://github.com/aTechGeekDev/ios-apollo) at
`f75f381e31da96de537653fbac2252d2eb80418`, which targets the same SM8250
(kona) SoC and iOS 16.7.16 userland.

The apollo port uses `MACHINE_CONFIG=SWEET` with SM8250 CPU/UFS/display
patches on top. munch shares the CPU topology (4x Cortex-A77 + 4x Cortex-A55),
UFS host, display controller and A650 GPU. The touch controller differs
(FocalTech on munch, Novatek on apollo); the apollo touch patches are kept for
now but will not bind on munch.

This is a bring-up set, not a qualified munch kernel:

- expect it to reach early kernel/framebuffer output;
- GPU/Wi-Fi/Bluetooth/audio patches are apollo-specific and may not bind;
- the munch touch controller still needs its own driver.

The GitHub Actions workflow `build-xnu-ios16.yml` stages these patches instead
of the sweet set when `xnu/patches-munch/` is present.
