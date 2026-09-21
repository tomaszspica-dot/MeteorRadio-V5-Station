# RMOB exporter

`software/meteorradio-rmob/rmob_utc_export.py` provides an independent export layer for monthly radio-meteor count data.

The public source uses a generic station identity.

Operators should configure their own station information and independently verify the current RMOB onboarding or upload procedure before submitting data.

The exporter does not access or control the RTL-SDR directly.
