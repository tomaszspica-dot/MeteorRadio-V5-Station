# Upstream GPLv3 publication checklist

Use this checklist before adding the locally modified MeteorRadio acquisition core to the public V5 tree or preparing an upstream pull request.

## Provenance

- [ ] record the exact `rabssm/MeteorRadio` base commit used by the V5 station
- [ ] identify every upstream file that was copied or modified
- [ ] keep the original copyright notices
- [ ] keep the applicable GPLv3 notices
- [ ] record the V5 modification date and a concise description of material changes

## GPLv3 distribution

- [ ] include the applicable GPLv3 license text with the distributed upstream-derived component
- [ ] make the complete corresponding source available as required by GPLv3
- [ ] do not impose additional restrictions inconsistent with GPLv3
- [ ] ensure generated packages/releases do not omit required source or notices

## V5 core audit

- [ ] diff the local modified `meteor_radar.py` against the recorded upstream base
- [ ] isolate `ADAPTIVE_CAPTURE_V2` and other acquisition-core changes from unrelated machine-specific edits
- [ ] remove credentials, coordinates, hostnames and local paths that should not be public
- [ ] verify the modified core still works with the documented V5 station layer
- [ ] update `docs/CODE_PROVENANCE.md` with the exact base commit and affected files

## Upstream contribution

- [ ] prepare a focused patch / branch for improvements that are useful to upstream MeteorRadio
- [ ] keep station-specific dashboards, scoring, retention and deployment changes out of the core PR unless they are directly relevant
- [ ] explain the behavioral change and testing performed
- [ ] reference upstream issue #14 where appropriate

Completing this checklist is the point at which the current validator/layout rule that prevents accidental vendoring of the upstream core can be intentionally revised.
