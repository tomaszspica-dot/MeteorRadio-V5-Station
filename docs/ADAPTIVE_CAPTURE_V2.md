# Adaptive Capture V2

The reference V5 station replaces a fixed post-trigger recording window with a dynamic capture strategy.

## Verified reference behaviour

The successful V2 deployment and runtime verification confirm:

```text
PRE context             1.5 s
minimum POST            0.8 s
quiet/hang interval     1.0 s
maximum POST            10.0 s
release behaviour       about 33% of the trigger threshold, with a minimum ratio of 12
rolling buffer          enlarged to preserve pre-trigger context
```

A capture starts after the trigger requirement is met. While active, sufficiently strong signal refreshes the last-signal time. Capture ends when either:

- the maximum post-trigger duration is reached, or
- the minimum post time has elapsed and the signal has remained below the release threshold for the hang interval.

The saved SMP includes reference metadata indicating adaptive capture and trigger timing.

## Why the exact threshold expression is not reproduced here

The exact modified acquisition implementation lives in the local upstream-derived `meteor_radar.py`, which is intentionally retained only under `private_reference/` while upstream redistribution/licensing is unresolved.

To avoid documenting an exact implementation detail that could drift from the private reference, this public document records only behaviour and parameter values that were verified during the successful V2 deployment.

## Why this matters

A fixed short display window can hide long meteor trails, while a fixed long recording wastes storage on short events. Adaptive capture keeps pre-trigger context but allows the stored event to follow the actual signal duration up to the safety limit.

## Source publication note

The exact modified upstream acquisition file is intentionally retained only in `private_reference/` until upstream redistribution rights are clarified.
