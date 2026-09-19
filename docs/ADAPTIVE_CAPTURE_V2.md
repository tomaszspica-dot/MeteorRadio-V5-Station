# Adaptive Capture V2

The reference V5 station replaces a fixed post-trigger recording window with a dynamic capture strategy.

## Reference parameters

```text
PRE context             1.5 s
minimum POST            0.8 s
quiet/hang interval     1.0 s
maximum POST            10.0 s
release factor          0.33
minimum release ratio   12.0
rolling buffer          40 sample blocks
```

The reference release threshold is derived from the configured SNR threshold using the equivalent logic:

```text
release_threshold = min(
    snr_threshold * 0.80,
    max(12.0, snr_threshold * 0.33)
)
```

A capture starts after the trigger requirement is met. While active, sufficiently strong signal refreshes the last-signal time. Capture ends when either:

- the maximum post-trigger duration is reached, or
- minimum post time has elapsed and the signal has remained below the release threshold for the hang interval.

The saved SMP includes reference metadata indicating adaptive capture and trigger timing.

## Why this matters

A fixed short display window can hide long meteor trails, while a fixed long recording wastes storage on short events. Adaptive capture keeps pre-trigger context but allows the stored event to follow the actual signal duration up to the safety limit.

## Source publication note

The exact modified upstream acquisition file is intentionally retained only in `private_reference/` until upstream redistribution rights are clarified.
