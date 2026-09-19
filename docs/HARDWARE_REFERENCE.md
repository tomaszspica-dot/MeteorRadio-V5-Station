# Hardware reference

The verified V5 reference station uses the following class of hardware:

- Raspberry Pi 4B, 2 GB RAM
- aarch64 Debian/Trixie-class OS
- RTL-SDR Blog V4 USB receiver
- Diamond X30 VHF/UHF antenna
- low-noise amplifier (LaNA)
- 50-ohm RF cabling/adapters
- stable Raspberry Pi power supply
- network connectivity for administration and time synchronization

## Frequency

The station receives meteor-scatter echoes of the GRAVES carrier around:

**143.050 MHz**

## Antenna note

The upstream MeteorRadio documentation recommends a 2-element HB9CV-type antenna for 143.05 MHz. The reference station documented here uses a Diamond X30 as a practical broadband installation. Users building a dedicated meteor station may choose a directional antenna optimized for 2 m instead.

## What should be documented in the GitHub repo

Recommended public hardware information:

- Raspberry Pi model
- SDR model
- antenna model/type
- whether an LNA is used
- approximate RF-chain topology
- operating frequency

Avoid publishing an exact home address or exact coordinates unless intentional.
