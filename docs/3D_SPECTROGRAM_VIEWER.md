# 3D Spectrogram Viewer — port 8099

The 3D Spectrogram Viewer is a read-only post-detection analysis service.

It reads saved NPZ observations and does not take ownership of the RTL-SDR device.

Features include:

- 3D and 2D representations of the same spectrogram matrix,
- selectable Doppler span,
- selectable FFT resolution,
- background-relative power,
- peak-Doppler indication,
- observation metadata.

High-resolution reference mode:

- FFT 8192,
- approximately 4.58 Hz/bin at 37.5 kS/s,
- high overlap for detailed visual inspection.

The viewer is an analysis tool and does not independently determine a meteor trajectory.
