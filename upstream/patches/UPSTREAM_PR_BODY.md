# Proposed upstream pull request

## Title

Add optional adaptive capture window for meteor detections

## Body

This adds an **opt-in adaptive capture mode** to `meteor_radar.py`.

The existing fixed-window capture behaviour remains unchanged by default.
Adaptive capture is enabled explicitly with:

```bash
--adaptivecapture
```

### What adaptive capture does

When enabled, MeteorRadio:

- keeps about **3.0 s of pre-trigger context**;
- requires at least **0.8 s after the first confirmed trigger**;
- continues recording while the signal remains above a lower release threshold;
- stops after **1.0 s of quiet** below that release threshold;
- applies a **10.0 s maximum post-trigger safety limit**;
- stores trigger/adaptive metadata in raw SMP NPZ files.

The lower release threshold provides hysteresis: the signal does not need to
remain above the original detection threshold for the capture to continue.

### Backward compatibility

Without `--adaptivecapture`, the original trigger wait and fixed
`SAMPLES_LENGTH` capture path is preserved.

Manual `SIGUSR1` saves also retain the original fixed-size snapshot even
when the larger adaptive rolling buffer is active.

### SMP metadata

Adaptive raw SMP captures add:

- `trigger_time`
- `adaptive_capture`
- `adaptive_pre_seconds`
- `adaptive_stop_reason`
- `adaptive_post_seconds`

Existing core fields (`obs_time`, `centre_freq`, `sample_rate`,
`samples`) are unchanged.

### Station testing

The adaptive capture approach was exercised on a Raspberry Pi 4 + RTL-SDR
GRAVES 143.050 MHz station before preparing this upstream candidate.

In one audit of the earlier adaptive implementation:

- 254 adaptive SMP files were present;
- median post-trigger duration was about 1.73 s;
- the inspected journal contained 59 adaptive stops, all 59 ending by
  signal fade rather than the maximum-post limit.

The upstream contribution was then rebased conceptually onto the current
MeteorRadio source and made opt-in to avoid changing existing installations.

### Validation for this candidate

Against the current upstream source:

- `git apply --check`: PASS
- patched file Git blob equals the reviewed candidate: PASS
- `python3 -m py_compile src/meteor_radar.py`: PASS
- V5 repository syntax/sanitization checks: PASS

### Scope intentionally left for a later PR

The V5 reference station also has a later **Adaptive Capture V3** extension
for long events (multi-tier limits and linked rollover segments). I have not
included that here so this first change stays small and reviewable.

Related licensing / contribution discussion: #14
