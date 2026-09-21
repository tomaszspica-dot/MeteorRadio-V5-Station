# Architecture

## RF and acquisition path

```mermaid
flowchart LR
    ANT[Diamond X30 reference antenna] --> LNA[LaNA / low-noise amplifier]
    LNA --> SDR[RTL-SDR Blog V4]
    SDR --> CORE[MeteorRadio acquisition core]
    CORE --> SMP[raw SMP detection files]
```

The exact coax/feedthrough arrangement is installation-specific and should be documented with a hardware photo rather than hard-coded into software.

## Processing path

```mermaid
flowchart TD
    A[meteor_radar acquisition] --> B[radar_data / SMP]
    B --> C[pre-render / renderer]
    B --> D[automatic score worker]
    D --> E[score index]
    E --> F[retention engine]
    E --> G[statistics]
    F --> H[favourites / manual deletion]
    C --> I[8094 main UI]
    D --> J[8095 queue/status]
    H --> K[8096 favourites]
    G --> L[8097 statistics]
    B --> N[8099 3D spectrogram analysis]
    N --> O[8100 trajectory-family analysis]
    B --> P[RMOB UTC exporter]
    A --> M[healthcheck]
```

## Optional shared-radio path

The reference station can share a single RTL-SDR with another receiver. `radio-owner-control` serializes ownership and `radio-owner-restore.service` restores the previously persisted owner after boot.

```mermaid
stateDiagram-v2
    [*] --> SONDEHUB
    SONDEHUB --> METEOR: switch to MeteorRadio
    METEOR --> SONDEHUB: switch to radiosonde receiver
    METEOR --> OFF: stop radio use
    SONDEHUB --> OFF: stop radio use
    OFF --> METEOR
    OFF --> SONDEHUB
```

On a dedicated MeteorRadio-only station this arbitration layer may be unnecessary.
