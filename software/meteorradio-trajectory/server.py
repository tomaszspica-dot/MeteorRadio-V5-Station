#!/usr/bin/env python3

# CODE PROVENANCE
# Contextual/scientific references reviewed during development:
#   https://github.com/bolidozor/trails-processing
#   https://github.com/bolidozor/MeteorDataAnalyser
#   https://github.com/bolidozor/RMDS02
#   https://github.com/carmelo-meteor/carmelo_meteor
# These are research/context references; the V5 8100 solver is independently
# implemented around single-station bistatic GRAVES geometry and Doppler data.
# See docs/CODE_PROVENANCE.md.


import json
import math
import os
import traceback
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np

try:
    from scipy.signal import (
        savgol_filter,
        butter,
        sosfiltfilt,
    )
    from scipy.optimize import minimize
except Exception:
    savgol_filter = None
    butter = None
    sosfiltfilt = None
    minimize = None


PORT = 8100
UPSTREAM = "http://127.0.0.1:8099"

RAW_ROOT = Path("/home/pi/radar_data")

C = 299792458.0
F0 = 143050000.0
LAMBDA = C / F0

EARTH_R_KM = 6371.0

# GRAVES public transmitter reference position.
# These defaults may be overridden through environment variables.
TX_LAT = float(
    os.environ.get(
        "METEORRADIO_TX_LAT",
        "47.3480"
    )
)

TX_LON = float(
    os.environ.get(
        "METEORRADIO_TX_LON",
        "5.5151"
    )
)


def required_env_float(name):

    value=os.environ.get(
        name
    )

    if value is None:

        raise RuntimeError(
            f"{name} must be configured "
            "for the local receiver station"
        )

    return float(
        value
    )


# Receiver coordinates are deliberately
# not embedded in the public source tree.
RX_LAT = required_env_float(
    "METEORRADIO_RX_LAT"
)

RX_LON = required_env_float(
    "METEORRADIO_RX_LON"
)

RX_ALT_KM = float(
    os.environ.get(
        "METEORRADIO_RX_ALT_KM",
        "0.0"
    )
)


def clamp(x, a, b):
    return max(a, min(b, x))


def haversine(lat1, lon1, lat2, lon2):
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2-lat1)
    dl = math.radians(lon2-lon1)

    a = (
        math.sin(dp/2.0)**2
        + math.cos(p1)*math.cos(p2)*math.sin(dl/2.0)**2
    )

    return 2.0 * EARTH_R_KM * math.asin(math.sqrt(a))


BASELINE_KM = haversine(
    TX_LAT, TX_LON,
    RX_LAT, RX_LON
)


def ecef(lat_deg, lon_deg, alt_km=0.0):
    lat = np.radians(lat_deg)
    lon = np.radians(lon_deg)

    r = EARTH_R_KM + alt_km

    return np.stack([
        r*np.cos(lat)*np.cos(lon),
        r*np.cos(lat)*np.sin(lon),
        r*np.sin(lat)
    ], axis=-1)


TX_ECEF = ecef(TX_LAT, TX_LON, 0.2)
RX_ECEF = ecef(
    RX_LAT,
    RX_LON,
    RX_ALT_KM
)


def params_to_pv(params):
    """
    params:
      latitude
      longitude
      altitude km
      speed km/s
      azimuth degrees
      downward angle degrees
    """

    a = np.asarray(params, dtype=float)

    one = (a.ndim == 1)

    if one:
        a = a[None, :]

    lat = np.radians(a[:, 0])
    lon = np.radians(a[:, 1])
    alt = a[:, 2]
    speed = a[:, 3]
    az = np.radians(a[:, 4])
    gamma = np.radians(a[:, 5])

    up = np.stack([
        np.cos(lat)*np.cos(lon),
        np.cos(lat)*np.sin(lon),
        np.sin(lat)
    ], axis=1)

    east = np.stack([
        -np.sin(lon),
        np.cos(lon),
        np.zeros_like(lon)
    ], axis=1)

    north = np.stack([
        -np.sin(lat)*np.cos(lon),
        -np.sin(lat)*np.sin(lon),
        np.cos(lat)
    ], axis=1)

    p = (EARTH_R_KM + alt)[:, None] * up

    horizontal = (
        np.cos(az)[:, None]*north
        + np.sin(az)[:, None]*east
    )

    v = (
        speed[:, None]*np.cos(gamma)[:, None]*horizontal
        - speed[:, None]*np.sin(gamma)[:, None]*up
    )

    if one:
        return p[0], v[0]

    return p, v


def model_batch(params, dt, observed):
    """
    v0.8 — prostoliniowy tor ECEF z podpisanym
    przyspieszeniem wzdłuż osi lotu.

    params:
      0 lat midpoint
      1 lon midpoint
      2 alt midpoint [km]
      3 speed w chwili midpoint [km/s]
      4 azimuth [deg]
      5 down angle [deg]
      6 along-track acceleration [km/s^2]

    a < 0  -> deceleracja
    a > 0  -> przyspieszanie
    """

    params=np.asarray(
        params,
        dtype=float
    )

    # params_to_pv nadal dostaje swoje oryginalne 6 parametrów.
    p, v0 = params_to_pv(
        params[:, :6]
    )


    if params.shape[1] >= 7:

        accel_scalar=params[:, 6]

    else:

        accel_scalar=np.zeros(
            len(params),
            dtype=float
        )


    speed0=np.linalg.norm(
        v0,
        axis=1
    )

    unit_v=(
        v0
        /
        np.maximum(
            speed0[:, None],
            1e-12
        )
    )


    accel_vec=(
        unit_v
        *
        accel_scalar[:, None]
    )


    tau=dt[None, :, None]


    pos=(
        p[:, None, :]
        +
        v0[:, None, :]*tau
        +
        0.5
        *
        accel_vec[:, None, :]
        *
        tau*tau
    )


    vel=(
        v0[:, None, :]
        +
        accel_vec[:, None, :]
        *
        tau
    )


    tx_vec=(
        pos
        -
        TX_ECEF[None, None, :]
    )

    rx_vec=(
        pos
        -
        RX_ECEF[None, None, :]
    )


    tx_dist=np.linalg.norm(
        tx_vec,
        axis=2
    )

    rx_dist=np.linalg.norm(
        rx_vec,
        axis=2
    )


    u_tx=(
        tx_vec
        /
        np.maximum(
            tx_dist[:, :, None],
            1e-9
        )
    )

    u_rx=(
        rx_vec
        /
        np.maximum(
            rx_dist[:, :, None],
            1e-9
        )
    )


    # Pochodna sumy dróg bistatycznych.
    dldt=np.sum(
        vel
        *
        (
            u_tx
            +
            u_rx
        ),
        axis=2
    )


    # km/s -> m/s
    doppler=(
        -(dldt*1000.0)
        /
        LAMBDA
    )


    # Pozostawiamy dotychczasowy niewielki bias.
    bias=np.mean(
        observed[None, :]
        -
        doppler,
        axis=1
    )

    bias=np.clip(
        bias,
        -40.0,
        40.0
    )


    prediction=(
        doppler
        +
        bias[:, None]
    )


    rmse=np.sqrt(
        np.mean(
            (
                prediction
                -
                observed[None, :]
            )**2,
            axis=1
        )
    )


    # --------------------------------------------------------------
    # Fizyczne zabezpieczenia.
    # --------------------------------------------------------------

    alt_path=(
        np.linalg.norm(
            pos,
            axis=2
        )
        -
        EARTH_R_KM
    )


    speed_path=np.linalg.norm(
        vel,
        axis=2
    )


    bad=(
        (
            np.min(
                alt_path,
                axis=1
            )
            <
            45.0
        )
        |
        (
            np.max(
                alt_path,
                axis=1
            )
            >
            145.0
        )
        |
        (
            np.min(
                speed_path,
                axis=1
            )
            <
            5.0
        )
        |
        (
            np.max(
                speed_path,
                axis=1
            )
            >
            80.0
        )
    )


    rmse[bad] += 500.0


    return (
        rmse,
        prediction,
        bias
    )


def model_one(params, dt, observed):
    q = np.asarray(params, dtype=float)[None, :]
    rmse, pred, bias = model_batch(
        q, dt, observed
    )

    return (
        float(rmse[0]),
        pred[0],
        float(bias[0])
    )


def upstream_json(path):
    url = UPSTREAM + path

    req = urllib.request.Request(
        url,
        headers={
            "User-Agent":
            "MeteorRadio-Trajectory/0.1"
        }
    )

    with urllib.request.urlopen(
        req,
        timeout=20
    ) as r:
        return json.loads(
            r.read().decode("utf-8")
        )


def find_matrix(obj, nt, nf, path="root", depth=0):
    if depth > 3:
        return None

    if isinstance(obj, dict):
        preferred = [
            "power_db",
            "power",
            "spectrogram",
            "matrix",
            "z_db",
            "z",
            "db",
            "values",
        ]

        keys = (
            preferred
            + [k for k in obj if k not in preferred]
        )

        for k in keys:
            if k not in obj:
                continue

            v = obj[k]

            try:
                a = np.asarray(v, dtype=float)

                if a.ndim == 2:
                    if a.shape == (nt, nf):
                        return a, path+"."+k

                    if a.shape == (nf, nt):
                        return a.T, path+"."+k

            except Exception:
                pass

            if isinstance(v, dict):
                got = find_matrix(
                    v, nt, nf,
                    path+"."+k,
                    depth+1
                )

                if got is not None:
                    return got

    return None


def extract_ridge(spec):
    """
    Ridge extractor v2.

    Nie szukamy już najdłuższej jasnej ścieżki w całym waterfallu.
    Kotwiczymy się w:
      - trigger_offset_s
      - peak_freq_hz

    Następnie śledzimy ciągły ślad w obie strony od najmocniejszego
    punktu w otoczeniu triggera.
    """

    if "freq_hz" not in spec:
        raise RuntimeError("8099 nie zwrócił freq_hz")

    if "time_s" not in spec:
        raise RuntimeError("8099 nie zwrócił time_s")

    freq=np.asarray(spec["freq_hz"],dtype=float)
    times=np.asarray(spec["time_s"],dtype=float)

    if freq.ndim != 1 or times.ndim != 1:
        raise RuntimeError("Nieprawidłowe osie spektrogramu")

    got=find_matrix(
        spec,
        len(times),
        len(freq)
    )

    if got is None:
        raise RuntimeError(
            "Nie znaleziono macierzy mocy w odpowiedzi 8099"
        )

    matrix,matrix_key=got

    matrix=np.asarray(matrix,dtype=float)

    finite=np.isfinite(matrix)

    if not np.any(finite):
        raise RuntimeError(
            "Macierz spektrogramu nie zawiera danych"
        )

    floor=float(
        np.nanpercentile(
            matrix[finite],
            5
        )
    )

    matrix=np.nan_to_num(
        matrix,
        nan=floor,
        posinf=floor,
        neginf=floor
    )

    # Usuń stałe tło częstotliwościowe.
    background=np.percentile(
        matrix,
        25,
        axis=0
    )

    energy=matrix-background[None,:]

    # lekkie wygładzenie tylko w osi częstotliwości
    if energy.shape[1] >= 3:
        e=energy.copy()

        e[:,1:-1]=(
            energy[:,:-2]
            + 2.0*energy[:,1:-1]
            + energy[:,2:]
        )/4.0

        energy=e

    meta=spec.get("meta",{})

    if not isinstance(meta,dict):
        meta={}

    try:
        trigger=float(
            meta.get("trigger_offset_s")
        )
    except Exception:
        trigger=float("nan")

    try:
        peak_freq=float(
            meta.get("peak_freq_hz")
        )
    except Exception:
        peak_freq=float("nan")

    # ----------------------------------------------------------
    # 1. OBSZAR SZUKANIA KOTWICY
    #
    # Meteor może zacząć się wyraźnie PRZED chwilą triggera,
    # dlatego patrzymy 1.35 s wstecz.
    # ----------------------------------------------------------

    if np.isfinite(trigger):

        # v3:
        # trigger jest momentem zadziałania detektora,
        # a nie gwarantowanym maksimum właściwego echa.
        #
        # Szukamy od 1.5 s przed triggerem
        # aż do końca zarejestrowanej detekcji.
        #
        # Dzięki temu długie overdense echo,
        # którego maksimum pojawia się po triggerze,
        # nie zostanie pominięte.

        search_start=max(
            float(times[0]),
            trigger-1.50
        )

        search_end=float(
            times[-1]
        )

        time_candidates=np.flatnonzero(
            (times >= search_start)
            &
            (times <= search_end)
        )

    else:
        search_start=float(times[0])
        search_end=float(times[-1])

        time_candidates=np.arange(
            len(times)
        )

    if time_candidates.size < 3:
        time_candidates=np.arange(
            len(times)
        )

    if np.isfinite(peak_freq):
        freq_candidates=np.flatnonzero(
            np.abs(freq-peak_freq)
            <= 100.0
        )
    else:
        freq_candidates=np.flatnonzero(
            np.abs(freq) <= 300.0
        )

    if freq_candidates.size < 3:
        freq_candidates=np.arange(
            len(freq)
        )

    candidate=energy[
        np.ix_(
            time_candidates,
            freq_candidates
        )
    ]

    if candidate.size == 0:
        raise RuntimeError(
            "Brak danych w obszarze kotwicy"
        )

    # ----------------------------------------------------------
    # 2. KOTWICA = najmocniejszy punkt blisko triggera i peak Hz
    # ----------------------------------------------------------

    flat=int(
        np.argmax(candidate)
    )

    ai,af=np.unravel_index(
        flat,
        candidate.shape
    )

    anchor_t=int(
        time_candidates[ai]
    )

    anchor_f=int(
        freq_candidates[af]
    )

    anchor_amp=float(
        energy[anchor_t,anchor_f]
    )

    # ----------------------------------------------------------
    # 3. PRÓG SYGNAŁU
    # ----------------------------------------------------------

    median=float(
        np.median(energy)
    )

    mad=float(
        np.median(
            np.abs(
                energy-median
            )
        )
    ) + 1e-6

    threshold=max(
        1.5,
        median+3.5*mad,
        0.24*anchor_amp
    )

    bin_hz=float(
        np.median(
            np.abs(
                np.diff(freq)
            )
        )
    )

    if (
        not np.isfinite(bin_hz)
        or bin_hz <= 0
    ):
        bin_hz=10.0

    # Przy 4096 FFT to zwykle 9.16 Hz/bin.
    # Pozwalamy maks. ~35 Hz zmiany na pojedynczy krok.
    max_jump=int(
        np.clip(
            np.ceil(
                35.0/bin_hz
            ),
            2,
            5
        )
    )

    max_gap=18

    # ----------------------------------------------------------
    # 4. TRACKER W JEDNYM KIERUNKU
    # ----------------------------------------------------------

    def follow(direction):

        points=[]

        prev=anchor_f
        prev_slope=0.0
        misses=0

        ti=anchor_t+direction

        while 0 <= ti < len(times):

            predicted=(
                prev
                + int(
                    round(
                        prev_slope
                    )
                )
            )

            lo=max(
                0,
                predicted-max_jump
            )

            hi=min(
                len(freq),
                predicted+max_jump+1
            )

            if hi <= lo:
                break

            bins=np.arange(
                lo,
                hi
            )

            values=energy[
                ti,
                lo:hi
            ]

            jump=(
                bins-prev
            )

            slope_error=(
                jump-prev_slope
            )

            # Jasność jest najważniejsza.
            # Dwa małe człony karzą gwałtowne skoki.
            score=(
                values
                - 0.18*np.abs(jump)
                - 0.10*np.abs(slope_error)
            )

            k=int(
                np.argmax(score)
            )

            fi=int(
                bins[k]
            )

            amp=float(
                energy[ti,fi]
            )

            if amp >= threshold:

                step=float(
                    fi-prev
                )

                prev_slope=(
                    0.65*prev_slope
                    + 0.35*step
                )

                prev=fi
                misses=0

                points.append(
                    (
                        ti,
                        fi,
                        amp
                    )
                )

            else:
                misses+=1

                # Krótka dziura może wystąpić w śladzie.
                if misses > max_gap:
                    break

            ti+=direction

        return points

    left=follow(-1)
    right=follow(+1)

    points=(
        list(reversed(left))
        + [
            (
                anchor_t,
                anchor_f,
                anchor_amp
            )
        ]
        + right
    )

    if len(points) < 6:
        raise RuntimeError(
            "Za mało punktów ciągłego śladu wokół triggera"
        )

    ti=np.asarray(
        [p[0] for p in points],
        dtype=int
    )

    fi=np.asarray(
        [p[1] for p in points],
        dtype=int
    )

    amp=np.asarray(
        [p[2] for p in points],
        dtype=float
    )

    ridge_time=times[ti]
    ridge_freq=freq[fi]

    # ----------------------------------------------------------
    # 5. WYGŁADZENIE SAMEJ LINII
    # ----------------------------------------------------------

    if (
        savgol_filter is not None
        and len(ridge_freq) >= 7
    ):

        win=min(
            11,
            len(ridge_freq)
            if len(ridge_freq)%2
            else len(ridge_freq)-1
        )

        if win >= 5:
            ridge_freq=savgol_filter(
                ridge_freq,
                win,
                2
            )

    # ----------------------------------------------------------
    # 6. ZACHOWUJEMY PEŁNY RIDGE
    #
    # v0.6:
    # Segmentacja CHIRP/TRAIL musi pracować na pełnej
    # rozdzielczości czasowej. Dopiero POTEM redukujemy
    # właściwy fragment do maks. 70 pkt dla solvera.
    # ----------------------------------------------------------

    ridge_time_full=np.asarray(
        ridge_time,
        dtype=float
    )

    ridge_freq_full=np.asarray(
        ridge_freq,
        dtype=float
    )

    ridge_amp_full=np.asarray(
        amp,
        dtype=float
    )


    n=min(
        70,
        len(ridge_time_full)
    )

    take=np.unique(
        np.linspace(
            0,
            len(ridge_time_full)-1,
            n
        ).astype(int)
    )

    return {
        "time":
            ridge_time_full[take],

        "freq":
            ridge_freq_full[take],

        "amp":
            ridge_amp_full[take],

        "time_full":
            ridge_time_full,

        "freq_full":
            ridge_freq_full,

        "amp_full":
            ridge_amp_full,

        "matrix_key":
            matrix_key,

        "threshold":
            float(threshold),

        "bin_hz":
            float(bin_hz),

        "full_points":
            int(len(ridge_time_full)),

        "anchor_time_s":
            float(times[anchor_t]),

        "anchor_freq_hz":
            float(freq[anchor_f]),

        "anchor_amp":
            float(anchor_amp),

        "trigger_offset_s":
            float(trigger)
            if np.isfinite(trigger)
            else None,

        "meta_peak_freq_hz":
            float(peak_freq)
            if np.isfinite(peak_freq)
            else None,

        "anchor_search_start_s":
            float(search_start),

        "anchor_search_end_s":
            float(search_end),
    }


def display_transform_latlon(lat, lon):
    ref_lat = math.radians(
        (TX_LAT+RX_LAT)/2.0
    )

    ref_lon = (
        TX_LON+RX_LON
    )/2.0

    ref_lat_deg = (
        TX_LAT+RX_LAT
    )/2.0

    def ground(lat1, lon1):
        east = (
            EARTH_R_KM
            * math.cos(ref_lat)
            * math.radians(
                lon1-ref_lon
            )
        )

        north = (
            EARTH_R_KM
            * math.radians(
                lat1-ref_lat_deg
            )
        )

        return np.array(
            [east, north],
            dtype=float
        )

    tx = ground(
        TX_LAT,
        TX_LON
    )

    rx = ground(
        RX_LAT,
        RX_LON
    )

    p = ground(
        float(lat),
        float(lon)
    )

    v = rx-tx

    source_angle = math.atan2(
        v[1],
        v[0]
    )

    axis = (
        BASELINE_KM
        / math.sqrt(2.0)
    )

    target = np.array(
        [-axis, axis]
    )

    target_angle = math.atan2(
        target[1],
        target[0]
    )

    angle = (
        target_angle
        - source_angle
    )

    ca = math.cos(angle)
    sa = math.sin(angle)

    rot = np.array([
        [ca, -sa],
        [sa, ca]
    ])

    source_len = max(
        np.linalg.norm(v),
        1e-9
    )

    scale = (
        BASELINE_KM
        / source_len
    )

    q = (
        rot @ (p-tx)
    ) * scale

    # GRAVES -> (axis,0)
    q += np.array(
        [axis, 0.0]
    )

    return q


def trajectory_for_display(params, dt):

    q=np.asarray(
        params,
        dtype=float
    )


    p0, v0 = params_to_pv(
        q[:6]
    )


    if q.size >= 7:

        accel_scalar=float(
            q[6]
        )

    else:

        accel_scalar=0.0


    speed0=float(
        np.linalg.norm(
            v0
        )
    )


    unit_v=(
        v0
        /
        max(
            speed0,
            1e-12
        )
    )


    accel_vec=(
        unit_v
        *
        accel_scalar
    )


    positions=(
        p0[None, :]
        +
        dt[:, None]
        *
        v0[None, :]
        +
        0.5
        *
        dt[:, None]**2
        *
        accel_vec[None, :]
    )


    rr=np.linalg.norm(
        positions,
        axis=1
    )


    lat=np.degrees(
        np.arcsin(
            positions[:, 2]
            /
            rr
        )
    )


    lon=np.degrees(
        np.arctan2(
            positions[:, 1],
            positions[:, 0]
        )
    )


    alt=(
        rr
        -
        EARTH_R_KM
    )


    result=[]


    for la,lo,al in zip(
        lat,
        lon,
        alt
    ):

        xy=display_transform_latlon(
            la,
            lo
        )

        result.append([
            float(xy[0]),
            float(xy[1]),
            float(al),
        ])


    return result



BOUNDS = [
    (45.0, 56.5),      # latitude
    (3.0, 19.0),       # longitude
    (55.0, 140.0),     # altitude km
    (11.0, 72.0),      # velocity at midpoint km/s
    (0.0, 360.0),      # azimuth
    (0.0, 70.0),       # downward angle
    (-80.0, 40.0),     # along-track acceleration km/s^2
]


def solve(ridge, filename, mc=8000, seed_salt=0):
    t = np.asarray(
        ridge["time"],
        dtype=float
    )

    observed = np.asarray(
        ridge["freq"],
        dtype=float
    )

    tmid = (
        t[0]+t[-1]
    )/2.0

    dt = t-tmid

    # stabilny seed zależny od nazwy detekcji
    seed = (
        (
            sum(
                (i+1)*ord(c)
                for i, c in enumerate(filename)
            )
            +
            int(seed_salt)*1000003
        )
        % (2**32-1)
    )

    rng = np.random.default_rng(
        seed
    )

    mc = int(
        clamp(mc, 1000, 30000)
    )

    params_all = np.empty(
        (mc, 7),
        dtype=float
    )

    params_all[:, 0] = rng.uniform(
        45.0, 56.5, mc
    )

    params_all[:, 1] = rng.uniform(
        3.0, 19.0, mc
    )

    params_all[:, 2] = rng.uniform(
        55.0, 140.0, mc
    )

    params_all[:, 3] = rng.uniform(
        11.0, 72.0, mc
    )

    params_all[:, 4] = rng.uniform(
        0.0, 360.0, mc
    )

    params_all[:, 5] = rng.uniform(
        0.0, 70.0, mc
    )

    # v0.8 signed along-track acceleration:
    # negative = deceleration.
    params_all[:, 6] = rng.uniform(
        -80.0, 40.0, mc
    )

    rmse_all = np.empty(
        mc,
        dtype=float
    )

    BATCH = 500

    for start in range(
        0,
        mc,
        BATCH
    ):
        end = min(
            mc,
            start+BATCH
        )

        r, _, _ = model_batch(
            params_all[start:end],
            dt,
            observed
        )

        rmse_all[start:end] = r

    best_index = int(
        np.argmin(rmse_all)
    )

    best_params = params_all[
        best_index
    ].copy()

    # lokalne dopracowanie najlepszego Monte Carlo
    if minimize is not None:
        def objective(x):
            return model_one(
                x,
                dt,
                observed
            )[0]

        try:
            opt = minimize(
                objective,
                best_params,
                method="Powell",
                bounds=BOUNDS,
                options={
                    "maxiter": 150,
                    "xtol": 1e-3,
                    "ftol": 1e-3,
                }
            )

            if (
                opt.success
                and np.isfinite(opt.fun)
                and opt.fun
                < rmse_all[best_index]
            ):
                best_params = (
                    np.asarray(
                        opt.x,
                        dtype=float
                    )
                )
        except Exception:
            pass

    best_rmse, prediction, bias = model_one(
        best_params,
        dt,
        observed
    )

    order = np.argsort(
        rmse_all
    )

    threshold = (
        best_rmse
        + max(
            5.0,
            0.35*best_rmse
        )
    )

    accepted = [
        int(i)
        for i in order
        if rmse_all[i] <= threshold
    ][:60]

    if len(accepted) < 20:
        accepted = [
            int(i)
            for i in order[:40]
        ]

    alt_times = np.linspace(
        dt[0],
        dt[-1],
        16
    )

    alternatives = []

    for i in accepted[:50]:
        pp = params_all[i]

        alternatives.append({
            "rmse_hz":
                float(rmse_all[i]),

            "path":
                trajectory_for_display(
                    pp,
                    alt_times
                )
        })

    best_times = np.linspace(
        dt[0],
        dt[-1],
        50
    )

    best_path = trajectory_for_display(
        best_params,
        best_times
    )

    p0, v0 = params_to_pv(
        best_params[:6]
    )

    accel_scalar=float(
        best_params[6]
    )

    speed_mid=float(
        np.linalg.norm(
            v0
        )
    )

    unit_v=(
        v0
        /
        max(
            speed_mid,
            1e-12
        )
    )

    accel_vec=(
        unit_v
        *
        accel_scalar
    )


    start_ecef=(
        p0
        +
        v0*dt[0]
        +
        0.5
        *
        accel_vec
        *
        dt[0]**2
    )

    end_ecef=(
        p0
        +
        v0*dt[-1]
        +
        0.5
        *
        accel_vec
        *
        dt[-1]**2
    )


    start_velocity=(
        v0
        +
        accel_vec*dt[0]
    )

    end_velocity=(
        v0
        +
        accel_vec*dt[-1]
    )


    speed_start=float(
        np.linalg.norm(
            start_velocity
        )
    )

    speed_end=float(
        np.linalg.norm(
            end_velocity
        )
    )


    start_alt=(
        np.linalg.norm(
            start_ecef
        )
        -
        EARTH_R_KM
    )

    end_alt=(
        np.linalg.norm(
            end_ecef
        )
        -
        EARTH_R_KM
    )

    axis = (
        BASELINE_KM
        / math.sqrt(2.0)
    )

    return {
        "model": (
            "single-station bistatic "
            "Monte-Carlo / ECEF + along-track acceleration v0.8"
        ),

        "warning": (
            "Jedna stacja + Doppler nie wyznaczają "
            "jednoznacznej trajektorii. Czerwony tor jest "
            "najlepszym dopasowaniem modelu, a nie dowodem "
            "rzeczywistej trajektorii meteoroidu."
        ),

        "baseline_km":
            BASELINE_KM,

        "lambda_m":
            LAMBDA,

        "monte_carlo":
            mc,

        "best": {
            "rmse_hz":
                best_rmse,

            "doppler_bias_hz":
                bias,

            "latitude_mid":
                float(best_params[0]),

            "longitude_mid":
                float(best_params[1]),

            "altitude_mid_km":
                float(best_params[2]),

            "speed_kms":
                float(best_params[3]),

            "azimuth_deg":
                float(best_params[4]),

            "down_angle_deg":
                float(best_params[5]),

            "along_track_accel_kms2":
                float(best_params[6]),

            "deceleration_kms2":
                float(
                    max(
                        0.0,
                        -best_params[6]
                    )
                ),

            "speed_start_kms":
                speed_start,

            "speed_mid_kms":
                speed_mid,

            "speed_end_kms":
                speed_end,

            "start_alt_km":
                float(start_alt),

            "end_alt_km":
                float(end_alt),

            "path":
                best_path,
        },

        "alternatives":
            alternatives,

        "geometry": {
            "axis_km":
                axis,

            "graves": [
                axis,
                0.0,
                0.0
            ],

            "station": [
                0.0,
                axis,
                0.0
            ],

            "z_max_km":
                130.0,
        },

        "doppler": {
            "time_s":
                [
                    float(x)
                    for x in t
                ],

            "observed_hz":
                [
                    float(x)
                    for x in observed
                ],

            "model_hz":
                [
                    float(x)
                    for x in prediction
                ],

            "amplitude":
                [
                    float(x)
                    for x in ridge["amp"]
                ],
        },
    }





def segment_ridge_for_trajectory(ridge):
    """
    Rozpoznaje morfologię:

        dynamiczny CHIRP  ->  długi, prawie stały TRAIL

    Zwraca:
      trajectory_ridge  — fragment do solvera 3D
      info              — opis segmentacji

    To klasyfikacja morfologii sygnału.
    Nie oznacza automatycznie, że dynamiczny fragment
    jest bezpośrednim echem samej bryły.
    """

    t=np.asarray(
        ridge.get(
            "time_full",
            ridge.get("time",[])
        ),
        dtype=float
    )

    f=np.asarray(
        ridge.get(
            "freq_full",
            ridge.get("freq",[])
        ),
        dtype=float
    )

    a=np.asarray(
        ridge.get(
            "amp_full",
            ridge.get("amp",[])
        ),
        dtype=float
    )

    n=len(t)


    info={
        "detected":False,
        "morphology":"SINGLE_COMPONENT",
        "trajectory_component":"FULL_RIDGE",
        "cut_index":None,

        "full_duration_s":
            float(t[-1]-t[0])
            if n >= 2
            else 0.0,

        "full_ridge_points":
            int(n),

        "head_full_points":None,
        "head_solver_points":None,

        "head_duration_s":None,
        "tail_duration_s":None,

        "head_span_hz":None,
        "tail_span_hz":None,
        "tail_slope_hz_s":None,
    }


    # Za mało punktów lub zbyt krótki event:
    # nie próbujemy dzielić.
    if n < 10:
        return ridge,info

    full_duration=float(
        t[-1]-t[0]
    )

    if full_duration < 1.5:
        return ridge,info


    # --------------------------------------------------------------
    # Wygładzona częstotliwość wyłącznie do decyzji o cięciu.
    # Do właściwego solvera pozostają oryginalne punkty ridge.
    # --------------------------------------------------------------

    fs=f.copy()

    if (
        savgol_filter is not None
        and n >= 9
    ):

        win=min(
            11,
            n if n%2 else n-1
        )

        if win >= 5:
            try:
                fs=savgol_filter(
                    f,
                    win,
                    2
                )
            except Exception:
                pass


    # --------------------------------------------------------------
    # Szukamy NAJWCZEŚNIEJSZEGO punktu, po którym:
    #
    # - początek miał duży span Dopplera,
    # - pozostała część trwa długo,
    # - trail jest relatywnie płaski,
    # - trail ma mały rozrzut częstotliwości.
    #
    # Dzięki "najwcześniejszemu" unikamy wciągania trailu
    # do segmentu trajektorii.
    # --------------------------------------------------------------

    candidate=None

    for k in range(4,n-5):

        head_t=t[:k+1]
        head_f=fs[:k+1]

        tail_t=t[k+1:]
        tail_f=fs[k+1:]


        head_duration=float(
            head_t[-1]-head_t[0]
        )

        tail_duration=float(
            tail_t[-1]-tail_t[0]
        )


        # Dynamiczny początek powinien być krótki.
        if head_duration < 0.05:
            continue

        if head_duration > 1.50:
            break


        # Musimy pozostawić prawdziwy długi trail.
        if tail_duration < 1.20:
            continue


        head_span=float(
            np.max(head_f)
            -
            np.min(head_f)
        )


        # Robust span trailu, odporny na pojedyncze skoki.
        tail_p10=float(
            np.percentile(
                tail_f,
                10
            )
        )

        tail_p90=float(
            np.percentile(
                tail_f,
                90
            )
        )

        tail_span=float(
            tail_p90-tail_p10
        )


        try:

            tail_slope=float(
                np.polyfit(
                    tail_t-tail_t[0],
                    tail_f,
                    1
                )[0]
            )

        except Exception:

            tail_slope=9999.0


        tail_median=float(
            np.median(
                tail_f
            )
        )


        # Początek trailu powinien być już blisko jego poziomu.
        transition_error=float(
            abs(
                fs[k]
                -
                tail_median
            )
        )


        # ----------------------------------------------------------
        # WARUNKI CHIRP + TRAIL
        # ----------------------------------------------------------

        dynamic_head=(
            head_span >= 80.0
        )

        stable_tail=(
            tail_span
            <= max(
                55.0,
                0.35*head_span
            )
        )

        low_tail_drift=(
            abs(tail_slope)
            <= 25.0
        )

        clean_transition=(
            transition_error
            <= 55.0
        )


        if (
            dynamic_head
            and stable_tail
            and low_tail_drift
            and clean_transition
        ):

            candidate={
                "k":k,
                "head_duration":
                    head_duration,

                "tail_duration":
                    tail_duration,

                "head_span":
                    head_span,

                "tail_span":
                    tail_span,

                "tail_slope":
                    tail_slope,
            }

            break


    if candidate is None:
        return ridge,info


    k=int(
        candidate["k"]
    )


    # --------------------------------------------------------------
    # Dodajemy 1 punkt przejściowy, jeżeli istnieje.
    # Pomaga uchwycić dojście do poziomu trailu.
    # --------------------------------------------------------------

    cut=min(
        n,
        k+2
    )


    tr=dict(ridge)

    head_time_full=t[:cut].copy()
    head_freq_full=f[:cut].copy()
    head_amp_full=a[:cut].copy()


    # ----------------------------------------------------------
    # Dopiero TERAZ redukujemy dynamiczny head do solvera.
    # ----------------------------------------------------------

    solver_n=min(
        70,
        len(head_time_full)
    )

    solver_take=np.unique(
        np.linspace(
            0,
            len(head_time_full)-1,
            solver_n
        ).astype(int)
    )


    tr["time_full"]=head_time_full
    tr["freq_full"]=head_freq_full
    tr["amp_full"]=head_amp_full

    tr["time"]=head_time_full[solver_take]
    tr["freq"]=head_freq_full[solver_take]
    tr["amp"]=head_amp_full[solver_take]

    tr["full_points"]=int(
        len(head_time_full)
    )


    info.update({
        "detected":True,

        "morphology":
            "CHIRP_PLUS_TRAIL",

        "trajectory_component":
            "DYNAMIC_HEAD",

        "cut_index":
            int(cut-1),

        "head_full_points":
            int(
                len(head_time_full)
            ),

        "head_solver_points":
            int(
                len(tr["time"])
            ),

        "head_duration_s":
            float(
                head_time_full[-1]
                -
                head_time_full[0]
            ),

        "tail_duration_s":
            float(
                t[-1]
                -
                t[cut-1]
            ),

        "head_span_hz":
            float(
                np.max(
                    tr["freq"]
                )
                -
                np.min(
                    tr["freq"]
                )
            ),

        "tail_span_hz":
            float(
                candidate[
                    "tail_span"
                ]
            ),

        "tail_slope_hz_s":
            float(
                candidate[
                    "tail_slope"
                ]
            ),
    })


    return tr,info



def refine_ridge_from_iq(filename, ridge, meta=None):
    """
    RAW IQ phase Doppler v0.8.

    FFT ridge służy jako coarse local oscillator.
    Po zdjęciu coarse Dopplera faza IQ wyznacza residual
    Doppler z rozdzielczością czasową 5 ms.

    Jeżeli test jakości nie przejdzie, funkcja zwraca
    oryginalny ridge FFT.
    """

    info={
        "attempted":False,
        "used":False,
        "source":"FFT_RIDGE",
        "reason":"not attempted",
        "step_ms":5.0,
        "original_points":int(
            len(
                ridge.get("time",[])
            )
        ),
    }


    if (
        butter is None
        or sosfiltfilt is None
        or savgol_filter is None
    ):

        info["reason"]="scipy signal unavailable"
        return ridge,info


    meta=meta if isinstance(meta,dict) else {}


    t=np.asarray(
        ridge.get(
            "time_full",
            ridge.get("time",[])
        ),
        dtype=float
    )

    f=np.asarray(
        ridge.get(
            "freq_full",
            ridge.get("freq",[])
        ),
        dtype=float
    )


    if len(t) < 4 or len(f) != len(t):

        info["reason"]="too few coarse ridge points"
        return ridge,info


    duration=float(
        t[-1]-t[0]
    )

    span=float(
        np.max(f)-np.min(f)
    )


    # Phase tracking ma sens dla krótkiego,
    # dynamicznego komponentu.
    if duration <= 0 or duration > 1.50:

        info["reason"]="ridge duration outside phase window"
        return ridge,info

    if span < 50.0:

        info["reason"]="Doppler span too small"
        return ridge,info


    info["attempted"]=True
    info["coarse_duration_s"]=duration
    info["coarse_span_hz"]=span


    path=RAW_ROOT / filename

    if not path.is_file():

        info["reason"]="NPZ file not found"
        return ridge,info


    try:

        with np.load(
            path,
            allow_pickle=False
        ) as z:

            samples=np.asarray(
                z["samples"],
                dtype=np.complex128
            )

            fs=float(
                z["sample_rate"]
            )

    except Exception as e:

        info["reason"]="NPZ read error: "+str(e)
        return ridge,info


    if fs <= 0 or len(samples) < 1000:

        info["reason"]="invalid RAW IQ"
        return ridge,info


    t0=float(t[0])
    t1=float(t[-1])

    margin=0.080


    i0=max(
        0,
        int(
            math.floor(
                (t0-margin)*fs
            )
        )
    )

    i1=min(
        len(samples),
        int(
            math.ceil(
                (t1+margin)*fs
            )
        )
    )


    if i1-i0 < 500:

        info["reason"]="RAW IQ window too short"
        return ridge,info


    raw=samples[i0:i1]

    tt=(
        np.arange(
            i0,
            i1,
            dtype=float
        )
        /
        fs
    )


    # ----------------------------------------------------------
    # FFT ridge -> coarse oscillator
    # ----------------------------------------------------------

    coarse=np.interp(
        tt,
        t,
        f,
        left=f[0],
        right=f[-1]
    )


    try:
        target=float(
            meta.get(
                "target_baseband_hz",
                2000.0
            )
        )
    except Exception:
        target=2000.0


    carrier=(
        target
        +
        coarse
    )


    phase_ref=(
        2.0*np.pi
        *
        np.cumsum(
            carrier
        )
        /
        fs
    )


    mixed=(
        raw
        *
        np.exp(
            -1j*phase_ref
        )
    )


    # ----------------------------------------------------------
    # Po coarse mixdown wystarczy wąski LPF.
    # ----------------------------------------------------------

    cutoff=160.0

    try:

        sos=butter(
            4,
            cutoff,
            btype="lowpass",
            fs=fs,
            output="sos"
        )

        bb=sosfiltfilt(
            sos,
            mixed
        )

    except Exception as e:

        info["reason"]="phase lowpass failed: "+str(e)
        return ridge,info


    amp=np.abs(
        bb
    )

    phase=np.unwrap(
        np.angle(
            bb
        )
    )


    # ----------------------------------------------------------
    # Pochodna fazy.
    # ~10 ms Savitzky-Golay.
    # ----------------------------------------------------------

    win=int(
        round(
            0.010*fs
        )
    )

    if win % 2 == 0:
        win+=1

    win=max(
        51,
        win
    )

    if win >= len(phase):
        win=len(phase)-1

    if win % 2 == 0:
        win-=1

    if win < 7:

        info["reason"]="phase window too short"
        return ridge,info


    try:

        residual=(
            savgol_filter(
                phase,
                win,
                3,
                deriv=1,
                delta=1.0/fs
            )
            /
            (2.0*np.pi)
        )

    except Exception as e:

        info["reason"]="phase derivative failed: "+str(e)
        return ridge,info


    refined=(
        coarse
        +
        residual
    )


    head=(
        (tt >= t0)
        &
        (tt <= t1)
    )

    pre=(
        (tt >= t0-0.070)
        &
        (tt < t0-0.015)
    )


    if not np.any(head):

        info["reason"]="no samples in head"
        return ridge,info


    head_amp=amp[head]

    med_head=float(
        np.median(
            head_amp
        )
    )


    if np.any(pre):

        med_pre=float(
            np.median(
                amp[pre]
            )
        )

    else:

        med_pre=float(
            np.percentile(
                amp,
                25
            )
        )


    snr_db=float(
        20.0*np.log10(
            max(
                med_head,
                1e-15
            )
            /
            max(
                med_pre,
                1e-15
            )
        )
    )


    amp_gate=float(
        np.percentile(
            head_amp,
            25
        )
    )


    correction=(
        refined
        -
        coarse
    )


    valid=(
        head
        &
        (amp >= amp_gate)
        &
        np.isfinite(refined)
        &
        (np.abs(correction) <= 120.0)
    )


    valid_samples=int(
        np.count_nonzero(
            valid
        )
    )


    if valid_samples < 100:

        info.update({
            "reason":"too few valid phase samples",
            "snr_db":snr_db,
            "valid_samples":valid_samples,
        })

        return ridge,info


    abs_corr=np.abs(
        correction[valid]
    )

    corr_med=float(
        np.median(
            abs_corr
        )
    )

    corr_p90=float(
        np.percentile(
            abs_corr,
            90
        )
    )

    corr_p99=float(
        np.percentile(
            abs_corr,
            99
        )
    )


    # ----------------------------------------------------------
    # Punkty co 5 ms.
    # ----------------------------------------------------------

    step=0.005

    grid=np.arange(
        t0,
        t1+step/2,
        step
    )


    rows=[]

    for g in grid:

        m=(
            valid
            &
            (
                np.abs(
                    tt-g
                )
                <= step/2
            )
        )

        count=int(
            np.count_nonzero(
                m
            )
        )

        if count == 0:
            continue


        weights=amp[m]

        sw=float(
            np.sum(
                weights
            )
        )

        if sw <= 0:
            continue


        freq_est=float(
            np.sum(
                refined[m]
                *
                weights
            )
            /
            sw
        )


        amp_est=float(
            np.mean(
                weights
            )
        )


        rows.append(
            (
                float(g),
                freq_est,
                amp_est,
                count
            )
        )


    phase_points=len(
        rows
    )


    usable=(
        phase_points >= 20
        and snr_db >= 3.0
        and corr_p90 <= 80.0
    )


    info.update({
        "snr_db":
            snr_db,

        "valid_samples":
            valid_samples,

        "phase_points":
            phase_points,

        "correction_median_abs_hz":
            corr_med,

        "correction_p90_abs_hz":
            corr_p90,

        "correction_p99_abs_hz":
            corr_p99,

        "filter_cutoff_hz":
            cutoff,

        "savgol_window_ms":
            float(
                1000.0*win/fs
            ),

        "sample_rate":
            fs,
    })


    if not usable:

        info["reason"]="phase quality gate failed"
        return ridge,info


    pt=np.asarray(
        [x[0] for x in rows],
        dtype=float
    )

    pf=np.asarray(
        [x[1] for x in rows],
        dtype=float
    )

    pa=np.asarray(
        [x[2] for x in rows],
        dtype=float
    )

    pc=np.asarray(
        [x[3] for x in rows],
        dtype=int
    )


    # Dodatkowy sanity check:
    # faza nie może stworzyć absurdalnie większego spanu.
    phase_span=float(
        np.max(pf)-np.min(pf)
    )

    if phase_span > max(
        500.0,
        2.0*span
    ):

        info["reason"]="phase Doppler span sanity check failed"
        return ridge,info


    out=dict(
        ridge
    )

    out["time"]=pt
    out["freq"]=pf
    out["amp"]=pa

    out["time_full"]=pt.copy()
    out["freq_full"]=pf.copy()
    out["amp_full"]=pa.copy()

    out["full_points"]=int(
        len(pt)
    )

    out["doppler_source"] = "RAW_IQ_PHASE_5MS"
    info.update({
        "used":True,
        "source":"RAW_IQ_PHASE_5MS",
        "reason":"quality gate passed",
        "phase_span_hz":
            phase_span,

        "start_freq_hz":
            float(pf[0]),

        "end_freq_hz":
            float(pf[-1]),

        "point_sample_counts":[
            int(x)
            for x in pc
        ],
    })


    return out,info


def solve_ensemble(ridge, filename, mc=8000):
    """
    Kilka niezależnych uruchomień solvera.

    Celem nie jest znalezienie jednej najładniejszej trajektorii,
    tylko sprawdzenie, czy wiele niezależnych poszukiwań zbiega
    do podobnej geometrii.
    """

    requested_mc = int(
        clamp(mc, 3000, 30000)
    )

    restarts = 6

    trials_per_restart = max(
        1000,
        int(
            math.ceil(
                requested_mc / restarts
            )
        )
    )

    runs=[]

    for k in range(restarts):

        sol=solve(
            ridge,
            filename,
            mc=trials_per_restart,
            seed_salt=k
        )

        runs.append(sol)


    runs.sort(
        key=lambda x:
            float(
                x["best"]["rmse_hz"]
            )
    )

    best=runs[0]

    best_rmse=float(
        best["best"]["rmse_hz"]
    )


    # -------------------------------------------------------------
    # Rozwiązania praktycznie równoważne jakościowo.
    # -------------------------------------------------------------

    rmse_limit=(
        best_rmse
        +
        max(
            4.0,
            0.20*best_rmse
        )
    )

    near=[
        r
        for r in runs
        if float(
            r["best"]["rmse_hz"]
        ) <= rmse_limit
    ]


    # Potrzebujemy minimum 3 geometrii do sensownej oceny rozrzutu.
    if len(near) < 3:
        near=runs[:min(3,len(runs))]


    def values(key):

        return np.asarray(
            [
                float(
                    r["best"][key]
                )
                for r in near
            ],
            dtype=float
        )


    def percentile_range(key):

        a=values(key)

        return [
            float(
                np.percentile(a,10)
            ),
            float(
                np.percentile(a,90)
            )
        ]


    alt=values(
        "altitude_mid_km"
    )

    speed=values(
        "speed_kms"
    )

    az=values(
        "azimuth_deg"
    )

    down=values(
        "down_angle_deg"
    )

    accel=values(
        "along_track_accel_kms2"
    )

    lat=values(
        "latitude_mid"
    )

    lon=values(
        "longitude_mid"
    )


    alt_range=percentile_range(
        "altitude_mid_km"
    )

    speed_range=percentile_range(
        "speed_kms"
    )

    down_range=percentile_range(
        "down_angle_deg"
    )

    accel_range=percentile_range(
        "along_track_accel_kms2"
    )

    lat_range=percentile_range(
        "latitude_mid"
    )

    lon_range=percentile_range(
        "longitude_mid"
    )


    # Azymut jest cykliczny.
    # Mierzymy maksymalną różnicę względem najlepszego rozwiązania.
    best_az=float(
        best["best"]["azimuth_deg"]
    )

    az_delta=np.abs(
        (
            az
            -
            best_az
            +
            180.0
        )
        % 360.0
        -
        180.0
    )

    az_max_delta=float(
        np.max(az_delta)
    )


    alt_span=float(
        alt_range[1]
        -
        alt_range[0]
    )

    speed_span=float(
        speed_range[1]
        -
        speed_range[0]
    )

    down_span=float(
        down_range[1]
        -
        down_range[0]
    )

    accel_span=float(
        accel_range[1]
        -
        accel_range[0]
    )

    lat_span=float(
        lat_range[1]
        -
        lat_range[0]
    )

    lon_span=float(
        lon_range[1]
        -
        lon_range[0]
    )


    # -------------------------------------------------------------
    # GEOMETRY STABILITY
    #
    # To również wskaźnik heurystyczny, a nie prawdopodobieństwo.
    # -------------------------------------------------------------

    stability=100.0

    stability-=min(
        35.0,
        alt_span*1.4
    )

    stability-=min(
        15.0,
        speed_span*2.5
    )

    stability-=min(
        25.0,
        az_max_delta*0.8
    )

    stability-=min(
        20.0,
        down_span*0.8
    )

    stability-=min(
        10.0,
        accel_span*0.20
    )

    stability-=min(
        10.0,
        lat_span*2.0
    )

    stability-=min(
        10.0,
        lon_span*1.0
    )

    stability=max(
        0,
        min(
            100,
            int(round(stability))
        )
    )


    if stability >= 70:

        stability_label="HIGH"

    elif stability >= 40:

        stability_label="MODERATE"

    else:

        stability_label="LOW"


    # -------------------------------------------------------------
    # Do 3D przekazujemy najlepsze trajektorie niezależnych restartów.
    # To właśnie będzie właściwa rodzina rozwiązań.
    # -------------------------------------------------------------

    family=[]

    for r in near:

        family.append({
            "rmse_hz":
                float(
                    r["best"]["rmse_hz"]
                ),

            "path":
                r["best"]["path"],

            "altitude_mid_km":
                float(
                    r["best"]["altitude_mid_km"]
                ),

            "speed_kms":
                float(
                    r["best"]["speed_kms"]
                ),

            "azimuth_deg":
                float(
                    r["best"]["azimuth_deg"]
                ),

            "down_angle_deg":
                float(
                    r["best"]["down_angle_deg"]
                ),

            "along_track_accel_kms2":
                float(
                    r["best"]["along_track_accel_kms2"]
                ),
        })


    # Zachowujemy stare alternatywy diagnostycznie.
    best["mc_alternatives"]=best.get(
        "alternatives",
        []
    )

    # Na ekran 3D idzie teraz rodzina niezależnych rozwiązań.
    best["alternatives"]=family

    # Pokazujemy użytkownikowi faktyczny łączny budżet próbek.
    best["monte_carlo"]=(
        restarts
        *
        trials_per_restart
    )


    best["ensemble"]={
        "restarts":
            restarts,

        "trials_per_restart":
            trials_per_restart,

        "total_trials":
            restarts
            *
            trials_per_restart,

        "near_best_solutions":
            len(near),

        "best_rmse_hz":
            best_rmse,

        "accepted_rmse_limit_hz":
            float(rmse_limit),

        "rmse_min_hz":
            float(
                min(
                    r["best"]["rmse_hz"]
                    for r in runs
                )
            ),

        "rmse_max_hz":
            float(
                max(
                    r["best"]["rmse_hz"]
                    for r in near
                )
            ),

        "stability_score":
            stability,

        "stability_label":
            stability_label,

        "altitude_mid_km_p10_p90":
            alt_range,

        "speed_kms_p10_p90":
            speed_range,

        "down_angle_deg_p10_p90":
            down_range,

        "along_track_accel_kms2_p10_p90":
            accel_range,

        "latitude_deg_p10_p90":
            lat_range,

        "longitude_deg_p10_p90":
            lon_range,

        "azimuth_max_delta_deg":
            az_max_delta,

        "altitude_span_km":
            alt_span,

        "speed_span_kms":
            speed_span,

        "down_angle_span_deg":
            down_span,

        "along_track_accel_span_kms2":
            accel_span,

        "latitude_span_deg":
            lat_span,

        "longitude_span_deg":
            lon_span,
    }


    return best


def assess_trajectory_quality(solution):
    """
    Heurystyczna kontrola jakości.

    UWAGA:
    confidence_score NIE jest prawdopodobieństwem.
    Jest wskaźnikiem diagnostycznym dla jednej stacji radiowej.

    Maksymalny wynik celowo ograniczamy do 65/100,
    ponieważ pojedyncza stacja + Doppler nie wyznaczają
    jednoznacznej trajektorii 3D.
    """

    d = solution.get("doppler", {})
    b = solution.get("best", {})

    t = np.asarray(
        d.get("time_s", []),
        dtype=float
    )

    f = np.asarray(
        d.get("observed_hz", []),
        dtype=float
    )

    if len(t) < 2 or len(f) < 2:

        return {
            "echo_class": "INVALID",
            "echo_label": "INVALID / za mało danych",
            "trajectory_allowed": False,
            "confidence_score": 0,
            "confidence_label": "LOW",
            "confidence_is_probability": False,
            "duration_s": 0.0,
            "doppler_span_hz": 0.0,
            "drift_hz": 0.0,
            "mean_slope_hz_s": 0.0,
            "crosses_zero": False,
            "boundary_hits": [],
            "issues": [
                "Za mało punktów Dopplera"
            ],
            "message":
                "Za mało danych do wiarygodnej analizy trajektorii."
        }


    duration = float(
        t[-1] - t[0]
    )

    fmin = float(
        np.min(f)
    )

    fmax = float(
        np.max(f)
    )

    span = float(
        fmax - fmin
    )

    drift = float(
        f[-1] - f[0]
    )

    if duration > 1e-9:
        mean_slope = drift / duration
    else:
        mean_slope = 0.0

    crosses_zero = bool(
        fmin <= 0.0 <= fmax
    )


    # ================================================================
    # KLASYFIKACJA RIDGE
    #
    # To klasyfikacja robocza/geometrii sygnału, a nie oficjalna
    # klasyfikacja fizyczna meteoru.
    # ================================================================

    if duration >= 3.0:

        echo_class = "LONG_TRAIL"
        echo_label = "LONG TRAIL / długie echo śladu"
        trajectory_allowed = False

    elif (
        duration <= 1.20
        and span >= 80.0
    ):

        echo_class = "SHORT_CHIRP"
        echo_label = "SHORT CHIRP / dynamiczny Doppler"
        trajectory_allowed = True

    elif (
        duration <= 2.50
        and span >= 40.0
    ):

        echo_class = "DYNAMIC_ECHO"
        echo_label = "DYNAMIC ECHO"
        trajectory_allowed = True

    else:

        echo_class = "AMBIGUOUS"
        echo_label = "AMBIGUOUS / niejednoznaczne"
        trajectory_allowed = False


    # ================================================================
    # SPRAWDZENIE, CZY SOLVER PRZYKLEIŁ SIĘ DO GRANIC
    # ================================================================

    boundary_hits = []


    def check_boundary(label, value, bounds):

        try:
            value = float(value)
        except Exception:
            return

        lo, hi = bounds

        if not np.isfinite(value):
            return

        width = float(
            hi - lo
        )

        if width <= 0:
            return

        margin = 0.025 * width

        if value <= lo + margin:

            boundary_hits.append(
                f"{label} ≈ MIN ({value:.2f})"
            )

        elif value >= hi - margin:

            boundary_hits.append(
                f"{label} ≈ MAX ({value:.2f})"
            )


    check_boundary(
        "latitude",
        b.get("latitude_mid"),
        BOUNDS[0]
    )

    check_boundary(
        "longitude",
        b.get("longitude_mid"),
        BOUNDS[1]
    )

    check_boundary(
        "wysokość środka",
        b.get("altitude_mid_km"),
        BOUNDS[2]
    )

    check_boundary(
        "prędkość",
        b.get("speed_kms"),
        BOUNDS[3]
    )

    # azymut jest cykliczny — 0° == 360°,
    # więc nie traktujemy jego granicy jako problemu.

    check_boundary(
        "kąt zejścia",
        b.get("down_angle_deg"),
        BOUNDS[5]
    )

    check_boundary(
        "przyspieszenie wzdłuż toru",
        b.get("along_track_accel_kms2"),
        BOUNDS[6]
    )


    try:
        bias = float(
            b.get("doppler_bias_hz", 0.0)
        )
    except Exception:
        bias = 0.0

    if abs(bias) >= 38.0:

        boundary_hits.append(
            f"offset Dopplera ≈ LIMIT ({bias:.1f} Hz)"
        )


    # ================================================================
    # JAKOŚĆ FITU
    # ================================================================

    try:
        rmse = float(
            b.get("rmse_hz", 9999.0)
        )
    except Exception:
        rmse = 9999.0

    fit_scale = max(
        15.0,
        0.25 * span
    )

    fit_ratio = (
        rmse / fit_scale
        if fit_scale > 0
        else 999.0
    )


    issues = []

    if echo_class == "LONG_TRAIL":

        issues.append(
            "Długi ridge: sygnał może opisywać ewolucję "
            "zjonizowanego śladu zamiast ruchu bryły."
        )

    elif echo_class == "AMBIGUOUS":

        issues.append(
            "Doppler nie ma wystarczająco dynamicznego "
            "przebiegu do stabilnej rekonstrukcji 3D."
        )

    if boundary_hits:

        issues.append(
            "Solver dotknął granic przestrzeni parametrów."
        )

    if fit_ratio > 1.0:

        issues.append(
            "Model prostoliniowej trajektorii słabo opisuje ridge."
        )

    if len(t) < 10:

        issues.append(
            "Mała liczba punktów Dopplera."
        )


    # ================================================================
    # TRAJECTORY CONFIDENCE — HEURYSTYCZNY SCORE
    #
    # NIE JEST PRAWDOPODOBIEŃSTWEM.
    # Maks. 65/100 z powodu pojedynczej stacji.
    # ================================================================

    score = 65.0

    if echo_class == "DYNAMIC_ECHO":
        score -= 5.0

    if boundary_hits:
        score -= min(
            32.0,
            8.0 * len(boundary_hits)
        )

    if fit_ratio > 1.0:
        score -= 20.0

    elif fit_ratio > 0.50:
        score -= 10.0

    if len(t) < 10:
        score -= 10.0

    if echo_class == "LONG_TRAIL":
        score = min(
            score,
            8.0
        )

    elif echo_class == "AMBIGUOUS":
        score = min(
            score,
            20.0
        )

    elif echo_class == "INVALID":
        score = 0.0

    score = int(
        round(
            max(
                0.0,
                min(
                    65.0,
                    score
                )
            )
        )
    )


    if score >= 50:

        confidence_label = "MODERATE"

    elif score >= 25:

        confidence_label = "LIMITED"

    else:

        confidence_label = "LOW"


    if echo_class == "LONG_TRAIL":

        message = (
            "LONG TRAIL: rekonstrukcja lotu bryły 3D została "
            "zablokowana. Ridge jest długi i najpewniej opisuje "
            "trwałe echo zjonizowanego śladu. Waterfall oraz "
            "Doppler pozostają dostępne do analizy."
        )

    elif echo_class == "AMBIGUOUS":

        message = (
            "Sygnał jest niejednoznaczny. Trajektoria 3D została "
            "zablokowana, ponieważ sam Doppler nie daje stabilnego "
            "rozwiązania."
        )

    elif boundary_hits:

        message = (
            "Solver 3D jest aktywny, ale część parametrów znajduje "
            "się przy granicach wyszukiwania. Wynik traktuj jako "
            "ograniczone rozwiązanie modelowe."
        )

    else:

        message = (
            "Krótki dynamiczny Doppler nadaje się do testowania "
            "geometrii 3D. Nadal jest to rodzina rozwiązań jednej "
            "stacji, a nie jednoznaczna trajektoria."
        )


    return {
        "echo_class":
            echo_class,

        "echo_label":
            echo_label,

        "trajectory_allowed":
            bool(trajectory_allowed),

        "confidence_score":
            score,

        "confidence_label":
            confidence_label,

        "confidence_is_probability":
            False,

        "confidence_cap_single_station":
            65,

        "duration_s":
            duration,

        "doppler_min_hz":
            fmin,

        "doppler_max_hz":
            fmax,

        "doppler_span_hz":
            span,

        "drift_hz":
            drift,

        "mean_slope_hz_s":
            float(mean_slope),

        "crosses_zero":
            crosses_zero,

        "rmse_hz":
            rmse,

        "fit_scale_hz":
            float(fit_scale),

        "fit_ratio":
            float(fit_ratio),

        "boundary_hits":
            boundary_hits,

        "issues":
            issues,

        "message":
            message,
    }



def doppler_curvature_evidence(
    ridge,
    phase_tracking,
    quality,
):
    """
    v0.9

    Niezależna od geometrii 3D analiza KRZYWIZNY
    obserwowanego Dopplera.

    Porównujemy:
      A) f(t) liniowe
      B) f(t) kwadratowe

    Następnie:
      - liczymy BIC,
      - redukujemy N do N_eff na podstawie autokorelacji,
      - sprawdzamy spójność w kolejnych blokach czasu.

    WAŻNE:
    To NIE jest bezpośredni pomiar fizycznego
    przyspieszenia / hamowania bryły meteoroidu.
    """

    phase_tracking=(
        phase_tracking
        if isinstance(
            phase_tracking,
            dict
        )
        else {}
    )

    quality=(
        quality
        if isinstance(
            quality,
            dict
        )
        else {}
    )

    phase_used=bool(
        phase_tracking.get(
            "used",
            False
        )
    )

    source=phase_tracking.get(
        "source"
    )

    if not source:
        source=ridge.get(
            "doppler_source",
            "FFT_RIDGE"
        )


    out={
        "version":
            "1.0",

        "method":
            (
                "linear-vs-quadratic Doppler shape / "
                "effective-BIC + block consistency"
            ),

        "valid":
            False,

        "applicable":
            False,

        "phase_used":
            phase_used,

        "input_source":
            str(source),

        "evidence_level":
            "NONE",

        "shape_support":
            "NONE",

        "physical_acceleration_direct":
            False,

        "geometry_independent":
            True,

        "reason":
            None,

        "message":
            (
                "Analiza dotyczy krzywizny Dopplera. "
                "Nie jest bezpośrednim pomiarem "
                "fizycznego przyspieszenia meteoroidu."
            ),
    }


    # --------------------------------------------------------
    # Nie interpretujemy długiego trailu / zablokowanego
    # sygnału jako kinematyki bryły.
    # --------------------------------------------------------

    if not quality.get(
        "trajectory_allowed",
        False
    ):

        out["evidence_level"]="BLOCKED"

        out["reason"]=(
            "trajectory_not_allowed: "
            +
            str(
                quality.get(
                    "echo_class",
                    "UNKNOWN"
                )
            )
        )

        out["message"]=(
            "Analiza kinematyczna zablokowana dla tej "
            "morfologii. Długi lub niejednoznaczny ridge "
            "nie jest traktowany jako dalszy lot bryły."
        )

        return out


    t=np.asarray(
        ridge.get(
            "time",
            []
        ),
        dtype=float
    )

    f=np.asarray(
        ridge.get(
            "freq",
            []
        ),
        dtype=float
    )


    if len(t) != len(f):

        out["reason"]="time_freq_length_mismatch"
        return out


    good=(
        np.isfinite(t)
        &
        np.isfinite(f)
    )

    t=t[good]
    f=f[good]


    if len(t) < 8:

        out["reason"]="too_few_points"
        out["n_points"]=int(len(t))
        return out


    order=np.argsort(t)

    t=t[order]
    f=f[order]


    # Usuwamy ewentualne identyczne znaczniki czasu.
    keep=np.ones(
        len(t),
        dtype=bool
    )

    if len(t) > 1:
        keep[1:]=(
            np.diff(t)
            >
            1e-9
        )

    t=t[keep]
    f=f[keep]


    n=int(
        len(t)
    )


    if n < 8:

        out["reason"]="too_few_unique_time_points"
        out["n_points"]=n
        return out


    duration=float(
        t[-1]
        -
        t[0]
    )


    if (
        not np.isfinite(duration)
        or
        duration <= 0.0
    ):

        out["reason"]="invalid_duration"
        return out


    # --------------------------------------------------------
    # Centrowanie i normalizacja czasu poprawiają conditioning.
    # --------------------------------------------------------

    tc=float(
        np.mean(t)
    )

    x=t-tc

    scale=float(
        np.max(
            np.abs(x)
        )
    )


    if (
        not np.isfinite(scale)
        or
        scale <= 1e-9
    ):

        out["reason"]="time_scale_too_small"
        return out


    u=x/scale


    X1=np.column_stack([
        np.ones(n),
        u,
    ])

    X2=np.column_stack([
        np.ones(n),
        u,
        u*u,
    ])


    c1=np.linalg.lstsq(
        X1,
        f,
        rcond=None
    )[0]

    c2=np.linalg.lstsq(
        X2,
        f,
        rcond=None
    )[0]


    pred1=X1@c1
    pred2=X2@c2


    r1=f-pred1
    r2=f-pred2


    mse1=float(
        np.mean(
            r1*r1
        )
    )

    mse2=float(
        np.mean(
            r2*r2
        )
    )


    mse1=max(
        mse1,
        1e-30
    )

    mse2=max(
        mse2,
        1e-30
    )


    rmse1=float(
        math.sqrt(mse1)
    )

    rmse2=float(
        math.sqrt(mse2)
    )


    # ========================================================
    # EFEKTYWNA LICZBA NIEZALEŻNYCH PUNKTÓW
    # ========================================================

    def residual_neff(residual):

        r=np.asarray(
            residual,
            dtype=float
        )

        r=(
            r
            -
            np.mean(r)
        )


        nn=len(r)

        den=float(
            np.sum(
                r*r
            )
        )


        if (
            nn < 3
            or
            den <= 0.0
            or
            not np.isfinite(den)
        ):

            return (
                float(nn),
                1.0,
                0.0,
            )


        maxlag=min(
            40,
            max(
                1,
                nn//4
            )
        )


        positive_sum=0.0
        rho1=0.0


        for lag in range(
            1,
            maxlag+1
        ):

            rho=float(
                np.sum(
                    r[:-lag]
                    *
                    r[lag:]
                )
                /
                den
            )


            if lag == 1:
                rho1=rho


            # Conservative positive-sequence estimator.
            if (
                not np.isfinite(rho)
                or
                rho <= 0.0
            ):
                break


            positive_sum+=rho


        tau=float(
            1.0
            +
            2.0*positive_sum
        )


        neff=float(
            nn/tau
        )


        neff=max(
            3.0,
            min(
                float(nn),
                neff
            )
        )


        return (
            neff,
            tau,
            rho1,
        )


    neff1,tau1,rho1_lin=(
        residual_neff(
            r1
        )
    )

    neff2,tau2,rho1_quad=(
        residual_neff(
            r2
        )
    )


    # Bierzemy mniejszą z dwóch wartości N_eff.
    neff=float(
        min(
            neff1,
            neff2
        )
    )


    tau=float(
        max(
            tau1,
            tau2
        )
    )


    ratio=float(
        mse1/mse2
    )


    # Model kwadratowy ma o jeden parametr więcej.
    delta_bic_raw=float(
        n
        *
        math.log(ratio)
        -
        math.log(n)
    )


    delta_bic_eff=float(
        neff
        *
        math.log(ratio)
        -
        math.log(neff)
    )


    # ========================================================
    # SPÓJNOŚĆ W KOLEJNYCH FRAGMENTACH SYGNAŁU
    # ========================================================

    block_count=min(
        6,
        max(
            2,
            n//4
        )
    )


    edges=np.linspace(
        0,
        n,
        block_count+1,
        dtype=int
    )


    blocks=[]


    for i in range(
        block_count
    ):

        a=int(
            edges[i]
        )

        b=int(
            edges[i+1]
        )


        if b-a < 2:
            continue


        br1=r1[a:b]
        br2=r2[a:b]


        brmse1=float(
            np.sqrt(
                np.mean(
                    br1*br1
                )
            )
        )

        brmse2=float(
            np.sqrt(
                np.mean(
                    br2*br2
                )
            )
        )


        gain=float(
            brmse1
            -
            brmse2
        )


        blocks.append({
            "index":
                int(i+1),

            "start_index":
                a,

            "end_index":
                b,

            "rmse_linear_hz":
                brmse1,

            "rmse_quadratic_hz":
                brmse2,

            "gain_hz":
                gain,

            "quadratic_better":
                bool(
                    gain > 0.0
                ),
        })


    blocks_total=int(
        len(blocks)
    )

    blocks_better=int(
        sum(
            1
            for b in blocks
            if b[
                "quadratic_better"
            ]
        )
    )


    block_ratio=(
        float(
            blocks_better
            /
            blocks_total
        )
        if blocks_total
        else 0.0
    )


    # ========================================================
    # KRZYWIZNA
    #
    # f = c0 + c1*u + c2*u²
    # u = (t-tc)/scale
    #
    # d²f/dt² = 2*c2 / scale²
    # ========================================================

    curvature=float(
        2.0
        *
        c2[2]
        /
        (
            scale*scale
        )
    )


    slope_center=float(
        c2[1]
        /
        scale
    )


    if curvature > 0.0:

        curvature_direction="POSITIVE"

    elif curvature < 0.0:

        curvature_direction="NEGATIVE"

    else:

        curvature_direction="ZERO"


    # ========================================================
    # SIŁA WSPARCIA KSZTAŁTU
    # ========================================================

    if (
        delta_bic_eff >= 6.0
        and
        block_ratio >= (2.0/3.0)
    ):

        shape_support="STRONG"

    elif (
        delta_bic_eff > 0.0
        and
        block_ratio >= (2.0/3.0)
    ):

        shape_support="MODERATE"

    elif delta_bic_eff > 0.0:

        shape_support="WEAK"

    else:

        shape_support="NONE"


    # RAW IQ może dostać właściwy poziom evidence.
    # FFT pozostaje wynikiem eksploracyjnym.
    if phase_used:

        evidence_level=shape_support

    else:

        evidence_level=(
            "EXPLORATORY"
            if shape_support != "NONE"
            else "NONE"
        )


    if phase_used:

        if shape_support == "STRONG":

            message=(
                "Krzywizna Dopplera jest mocno wsparta także "
                "po korekcie na autokorelację i jest rozłożona "
                "w wielu fragmentach sygnału RAW IQ. "
                "Nie jest to jednak bezpośredni pomiar "
                "fizycznego przyspieszenia bryły."
            )

        elif shape_support == "MODERATE":

            message=(
                "Dane RAW IQ wspierają krzywiznę Dopplera, "
                "ale siła statystyczna jest umiarkowana. "
                "Nie należy utożsamiać znaku krzywizny "
                "z fizycznym przyspieszeniem meteoroidu."
            )

        else:

            message=(
                "RAW IQ nie daje obecnie mocnego, stabilnego "
                "wsparcia dla dodatkowej krzywizny Dopplera."
            )

    else:

        message=(
            "Wynik eksploracyjny z FFT ridge. "
            "Krzywizna może być opisana liczbowo, lecz "
            "najwyższą wagę diagnostyczną mają przypadki "
            "zakwalifikowane przez RAW IQ phase."
        )


    out.update({
        "valid":
            True,

        "applicable":
            True,

        "evidence_level":
            evidence_level,

        "shape_support":
            shape_support,

        "n_points":
            n,

        "duration_s":
            duration,

        "n_eff":
            neff,

        "correlation_time_factor":
            tau,

        "rho1_linear":
            float(
                rho1_lin
            ),

        "rho1_quadratic":
            float(
                rho1_quad
            ),

        "rmse_linear_hz":
            rmse1,

        "rmse_quadratic_hz":
            rmse2,

        "rmse_gain_hz":
            float(
                rmse1-rmse2
            ),

        "delta_bic_raw":
            delta_bic_raw,

        "delta_bic_eff":
            delta_bic_eff,

        "blocks_better":
            blocks_better,

        "blocks_total":
            blocks_total,

        "blocks_ratio":
            block_ratio,

        "blocks":
            blocks,

        "curvature_hz_s2":
            curvature,

        "curvature_direction":
            curvature_direction,

        "slope_center_hz_s":
            slope_center,

        "message":
            message,
    })


    return out


def analyze(filename, mc):
    if (
        not filename
        or Path(filename).name != filename
        or not filename.endswith(".npz")
    ):
        raise RuntimeError(
            "Nieprawidłowa nazwa pliku NPZ"
        )

    query = urllib.parse.urlencode({
        "file": filename,
        "span": "300",
        "fft": "4096",
    })

    spec = upstream_json(
        "/api/spectrogram?"
        + query
    )

    ridge = extract_ridge(
        spec
    )

    # ----------------------------------------------------------
    # Zachowujemy pełny ridge do prezentacji.
    # Solver może dostać tylko dynamiczny komponent początkowy.
    # ----------------------------------------------------------

    full_ridge=ridge

    ridge,segmentation=segment_ridge_for_trajectory(
        full_ridge
    )


    # ----------------------------------------------------------
    # v0.8:
    # FFT daje coarse ridge.
    # RAW IQ phase próbuje zagęścić Doppler do 5 ms.
    # W przypadku niepowodzenia ridge pozostaje bez zmian.
    # ----------------------------------------------------------

    ridge,phase_tracking=refine_ridge_from_iq(
        filename,
        ridge,
        spec.get(
            "meta",
            {}
        )
    )


    segmentation["solver_input_source"] = (
        phase_tracking.get(
            "source",
            "FFT_RIDGE"
        )
    )

    segmentation["solver_input_points"] = int(
        len(
            ridge.get(
                "time",
                []
            )
        )
    )


    solution = solve_ensemble(
        ridge,
        filename,
        mc=mc
    )


    solution["signal"]={
        "segmentation":
            segmentation,

        "phase_tracking":
            phase_tracking,

        "full_ridge":{
            "time_s":[
                float(x)
                for x in np.asarray(
                    full_ridge.get(
                        "time_full",
                        full_ridge["time"]
                    ),
                    dtype=float
                )
            ],

            "freq_hz":[
                float(x)
                for x in np.asarray(
                    full_ridge.get(
                        "freq_full",
                        full_ridge["freq"]
                    ),
                    dtype=float
                )
            ],
        },

        "trajectory_ridge":{
            "time_s":[
                float(x)
                for x in np.asarray(
                    ridge.get(
                        "time_full",
                        ridge["time"]
                    ),
                    dtype=float
                )
            ],

            "freq_hz":[
                float(x)
                for x in np.asarray(
                    ridge.get(
                        "freq_full",
                        ridge["freq"]
                    ),
                    dtype=float
                )
            ],
        },
    }


    solution["quality"] = assess_trajectory_quality(
        solution
    )

    ens=solution.get(
        "ensemble",
        {}
    )

    q=solution["quality"]

    segmentation=solution.get(
        "signal",
        {}
    ).get(
        "segmentation",
        {}
    )


    # ----------------------------------------------------------
    # Event zawiera pełny trail, ale geometria została policzona
    # tylko z dynamicznego początku.
    # ----------------------------------------------------------

    if segmentation.get(
        "detected",
        False
    ):

        q["trajectory_component_class"]=q.get(
            "echo_class"
        )

        q["echo_class"]="CHIRP_PLUS_TRAIL"

        q["echo_label"] = (
            "CHIRP + LONG TRAIL / 3D z dynamicznego początku"
        )

        q["trajectory_component"]="DYNAMIC_HEAD"

        q["full_event_duration_s"]=segmentation.get(
            "full_duration_s"
        )

        q["head_duration_s"]=segmentation.get(
            "head_duration_s"
        )

        q["tail_duration_s"]=segmentation.get(
            "tail_duration_s"
        )


    stability_label=ens.get(
        "stability_label",
        "LOW"
    )

    stability_score=int(
        ens.get(
            "stability_score",
            0
        )
    )


    # ----------------------------------------------------------
    # SHORT CHIRP może mieć dobry Doppler, ale słabo określoną
    # geometrię przestrzenną.
    # ----------------------------------------------------------

    if q.get(
        "trajectory_allowed",
        False
    ):

        if stability_label == "LOW":

            q["solution_mode"]="FAMILY_ONLY"

            q["confidence_score"]=min(
                int(
                    q.get(
                        "confidence_score",
                        0
                    )
                ),
                24
            )

            q["confidence_label"]="LOW"

            q.setdefault(
                "issues",
                []
            ).append(
                "Niezależne uruchomienia solvera dają "
                "różne geometrie o podobnym RMSE."
            )

            q["message"]=(
                "Doppler nadaje się do modelowania, ale geometria "
                "3D nie jest jednoznaczna. Pokazujemy rodzinę "
                "równoważnych trajektorii zamiast jednej "
                "trajektorii jako wyniku."
            )

        elif stability_label == "MODERATE":

            q["solution_mode"]="BEST_PLUS_FAMILY"

            q["confidence_score"]=min(
                int(
                    q.get(
                        "confidence_score",
                        0
                    )
                ),
                45
            )

            if q["confidence_score"] < 25:
                q["confidence_label"]="LOW"
            else:
                q["confidence_label"]="LIMITED"

        else:

            q["solution_mode"]="BEST_PLUS_FAMILY"

    else:

        q["solution_mode"]="BLOCKED"


    q["geometry_stability_score"]=stability_score
    q["geometry_stability_label"]=stability_label


    if segmentation.get(
        "detected",
        False
    ):

        q["message"]=(
            "Wykryto CHIRP + LONG TRAIL. "
            "Solver 3D wykorzystuje WYŁĄCZNIE krótki "
            "dynamiczny komponent początkowy; długi trail "
            "nie jest traktowany jako dalszy lot bryły. "
            +
            q.get(
                "message",
                ""
            )
        )

    # Gdy geometria nie nadaje się do rekonstrukcji bryły,
    # zastępujemy standardowe ostrzeżenie dokładniejszym komunikatem.
    if not solution["quality"]["trajectory_allowed"]:

        solution["warning"] = (
            solution["quality"]["message"]
            + " "
            + solution.get("warning", "")
        )

    elif solution["quality"]["boundary_hits"]:

        solution["warning"] = (
            solution["quality"]["message"]
            + " "
            + solution.get("warning", "")
        )

    # ----------------------------------------------------------
    # v0.9 — niezależne evidence kształtu Dopplera.
    # NIE wpływa na wynik solvera 3D.
    # ----------------------------------------------------------

    solution["kinematics_evidence"] = (
        doppler_curvature_evidence(
            ridge,
            phase_tracking,
            solution.get(
                "quality",
                {}
            ),
        )
    )

    solution["file"] = filename

    solution["ridge"] = {
        "matrix_key":
            ridge["matrix_key"],

        "doppler_source":
            ridge.get(
                "doppler_source",
                "FFT_RIDGE"
            ),

        "bin_hz":
            ridge["bin_hz"],

        "points":
            len(ridge["time"]),

        "full_points":
            ridge["full_points"],

        "detection_threshold":
            ridge["threshold"],

        "anchor_time_s":
            ridge.get("anchor_time_s"),

        "anchor_freq_hz":
            ridge.get("anchor_freq_hz"),

        "anchor_amp":
            ridge.get("anchor_amp"),

        "trigger_offset_s":
            ridge.get("trigger_offset_s"),

        "meta_peak_freq_hz":
            ridge.get("meta_peak_freq_hz"),

        "anchor_search_start_s":
            ridge.get("anchor_search_start_s"),

        "anchor_search_end_s":
            ridge.get("anchor_search_end_s"),
    }

    meta = spec.get(
        "meta",
        {}
    )

    if isinstance(meta, dict):
        solution["meta"] = meta

    return solution


INDEX = r'''<!doctype html>
<html lang="pl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">

<title>MeteorRadio 3D Trajectory Analyzer</title>

<style>
:root{
  color-scheme:dark;
  --bg:#071019;
  --panel:#0c1722;
  --line:#223546;
  --text:#e8f1f8;
  --muted:#8296a8;
  --blue:#2e91ff;
  --green:#53d273;
  --orange:#ff9d2e;
  --red:#ff4343;
}
*{box-sizing:border-box}
body{
  margin:0;
  background:var(--bg);
  color:var(--text);
  font:14px system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
}
header{
  height:58px;
  display:flex;
  align-items:center;
  gap:22px;
  padding:0 18px;
  border-bottom:1px solid var(--line);
  background:#09141e;
}
header h1{
  margin:0;
  font-size:19px;
}
.ver{color:var(--muted);font-size:12px}
.status{
  margin-left:auto;
  color:#77d78c;
}
.controls{
  display:flex;
  gap:12px;
  align-items:end;
  padding:12px 16px;
  border-bottom:1px solid var(--line);
}
label{
  display:flex;
  flex-direction:column;
  gap:5px;
  color:var(--muted);
  font-size:12px;
}
select,button{
  background:#122131;
  color:var(--text);
  border:1px solid #31475a;
  border-radius:6px;
  padding:9px 12px;
}
select{min-width:430px}
button{
  background:#1769e0;
  border-color:#3486ff;
  cursor:pointer;
  font-weight:600;
}
button:disabled{opacity:.5}
.grid{
  display:grid;
  grid-template-columns:minmax(600px,1fr) 350px;
  grid-template-rows:560px 300px 270px;
  gap:10px;
  padding:10px;
}
.panel{
  background:var(--panel);
  border:1px solid var(--line);
  border-radius:7px;
  overflow:hidden;
}
.panel h2{
  font-size:14px;
  margin:0;
  padding:10px 12px;
  border-bottom:1px solid var(--line);
}
#view3d{
  width:100%;
  height:515px;
  display:block;
  cursor:grab;
}
#waterfall{
  width:100%;
  height:255px;
  display:block;
}

#doppler{
  width:100%;
  height:225px;
  display:block;
}
.side{
  grid-column:2;
  grid-row:1 / span 3;
  padding:12px;
  overflow:auto;
}
.metric{
  display:grid;
  grid-template-columns:1fr auto;
  gap:8px;
  padding:8px 0;
  border-bottom:1px solid #182838;
}
.metric span:first-child{color:var(--muted)}
.warning{
  margin-top:14px;
  padding:12px;
  background:#241e11;
  border:1px solid #5e4a20;
  border-radius:6px;
  line-height:1.45;
}

.kinematics{
  border:1px solid #2e3b49;
  border-radius:10px;
  padding:12px;
  margin-bottom:12px;
  background:#0d141b;
}
.kin-head{
  display:flex;
  align-items:center;
  justify-content:space-between;
  gap:10px;
  font-weight:700;
}
.kin-badge{
  font-size:11px;
  padding:3px 7px;
  border-radius:999px;
  border:1px solid currentColor;
  white-space:nowrap;
}
.kin-grid{
  display:grid;
  grid-template-columns:1fr 1fr;
  gap:7px 12px;
  margin-top:10px;
}
.kin-item{
  font-size:12px;
  opacity:.95;
}
.kin-item span{
  display:block;
  opacity:.65;
  font-size:10px;
  text-transform:uppercase;
  letter-spacing:.04em;
}
.kin-note{
  margin-top:10px;
  font-size:11px;
  line-height:1.4;
  opacity:.78;
}
.kin-strong{
  border-color:#40b976;
}
.kin-moderate{
  border-color:#d6b34a;
}
.kin-exploratory{
  border-color:#6b91bd;
}
.kin-weak{
  border-color:#9b7b56;
}
.kin-none,
.kin-blocked{
  border-color:#626a73;
}

.quality{
  margin:0 0 12px 0;
  padding:12px;
  border-radius:7px;
  border:1px solid #394b5c;
  background:#101c28;
  line-height:1.45;
}

.quality-title{
  font-size:14px;
  font-weight:750;
  margin-bottom:5px;
}

.quality-score{
  font-size:22px;
  font-weight:800;
  margin:4px 0;
}

.quality-note{
  font-size:11px;
  color:#9fb1c0;
  margin-top:6px;
}

.quality-moderate{
  border-color:#3c7d59;
  background:#10251a;
}

.quality-limited{
  border-color:#806524;
  background:#28210f;
}

.quality-low{
  border-color:#864444;
  background:#2b1517;
}

.legend{
  padding:10px 12px;
  color:var(--muted);
  border-top:1px solid var(--line);
}
.dot{
  width:10px;height:10px;
  display:inline-block;
  border-radius:50%;
  margin-right:5px;
}
footer{
  display:flex;
  gap:28px;
  padding:9px 16px 13px;
  color:var(--muted);
  font-size:12px;
}
#message{color:#ffcf68}
</style>
</head>

<body>

<header>
  <h1>MeteorRadio 3D Trajectory Analyzer <span class="ver">v0.8</span></h1>
  <span>GRAVES 143.050 MHz</span>
  <span>Z = wysokość</span>
  <span class="status">● 8100</span>
</header>

<div class="controls">
  <label>
    Detekcja
    <select id="event"></select>
  </label>

  <label>
    Monte Carlo
    <select id="mc">
      <option value="3000">3 000 — szybki test</option>
      <option value="8000" selected>8 000 — standard</option>
      <option value="20000">20 000 — dokładniej</option>
    </select>
  </label>

  <button id="run">▶ Analizuj trajektorię</button>

  <span id="message"></span>
</div>

<div class="grid">

  <div class="panel">
    <h2>Trajektoria 3D — rodzina rozwiązań zgodnych z Dopplerem</h2>
    <canvas id="view3d"></canvas>
    <div class="legend">
      <span class="dot" style="background:#ff4343"></span>best fit
      &nbsp;&nbsp;
      <span class="dot" style="background:#777"></span>inne dopuszczalne tory
      &nbsp;&nbsp;
      <span class="dot" style="background:#2e91ff"></span>GRAVES
      &nbsp;&nbsp;
      <span class="dot" style="background:#53d273"></span>Twoja stacja
      &nbsp;&nbsp; • &nbsp;&nbsp;
      rolka = zoom
      &nbsp;&nbsp; • &nbsp;&nbsp;
      przeciągnij = obrót
      &nbsp;&nbsp; • &nbsp;&nbsp;
      Shift + przeciągnij = przesunięcie
      &nbsp;&nbsp; • &nbsp;&nbsp;
      dwuklik = reset
    </div>
  </div>

  <div class="panel">
    <h2>Waterfall — ślad rzeczywiście używany przez solver</h2>
    <canvas id="waterfall"></canvas>
    <div class="legend">
      <span class="dot" style="background:#ff9d2e"></span>FULL RIDGE
      &nbsp;&nbsp;
      <span class="dot" style="background:#ff3b30"></span>DOPPLER USED BY 3D
      &nbsp;&nbsp;
      <span style="color:#e7c75f">┊ trigger</span>
      &nbsp;&nbsp;
      <span style="color:#9fb3c4">--- 0 Hz</span>
    </div>
  </div>

  <div class="panel">
    <h2>Doppler — pomiar kontra model</h2>
    <canvas id="doppler"></canvas>
  </div>

  <div class="panel side">
    <h2 style="margin:-12px -12px 8px">Wynik solvera</h2>

    <div id="quality"
         class="quality quality-low">
      <div class="quality-title">
        TRAJECTORY CONFIDENCE
      </div>
      <div>
        Brak analizy.
      </div>
    </div>

    <div id="kinematics"
         class="kinematics kin-none">
      <div class="kin-head">
        <span>Doppler curvature / kinematics evidence</span>
        <span class="kin-badge">—</span>
      </div>
      <div class="kin-note">
        Wynik pojawi się po analizie.
      </div>
    </div>

    <div id="metrics"></div>
    <div class="warning" id="warning">
      Wybierz detekcję i uruchom analizę.
    </div>
  </div>

</div>

<footer>
  <span id="source">Źródło: MeteorRadio 8099</span>
  <span id="ridge"></span>
  <span id="calc"></span>
</footer>

<script>
const $ = q => document.querySelector(q);

let DATA=null;
let SPEC=null;

let yaw=-0.72;
let pitch=0.52;

let zoom3d=1.0;
let panX=0;
let panY=0;

let dragging=false;
let px=0,py=0;

function resizeCanvas(c){
  const dpr=window.devicePixelRatio||1;
  const r=c.getBoundingClientRect();
  c.width=Math.max(1,Math.round(r.width*dpr));
  c.height=Math.max(1,Math.round(r.height*dpr));
  const ctx=c.getContext("2d");
  ctx.setTransform(dpr,0,0,dpr,0,0);
  return {ctx,w:r.width,h:r.height};
}

async function loadEvents(){
  const j=await fetch("/api/events").then(r=>r.json());
  const events=Array.isArray(j) ? j : (j.events||j.items||[]);
  const sel=$("#event");
  sel.innerHTML="";

  for(const e of events){
    const file=e.file||e.filename||e.name;
    if(!file) continue;

    const o=document.createElement("option");
    o.value=file;
    o.textContent=(e.obs_time||file)+"  •  "+file;
    sel.appendChild(o);
  }

  if(!sel.options.length){
    const o=document.createElement("option");
    o.textContent="Brak detekcji";
    sel.appendChild(o);
  }
}

function project(p,w,h,rng){
  let x=(p[0]-rng.cx)/rng.s;
  let y=(p[1]-rng.cy)/rng.s;
  let z=(p[2]-rng.cz)/rng.s;

  const cy=Math.cos(yaw), sy=Math.sin(yaw);
  let x1=x*cy-y*sy;
  let y1=x*sy+y*cy;

  const cp=Math.cos(pitch), sp=Math.sin(pitch);
  let y2=y1*cp-z*sp;
  let z2=y1*sp+z*cp;

  const scale=Math.min(w,h)*0.82*zoom3d;

  return [
    w/2 + panX + x1*scale,
    h/2 + panY - y2*scale,
    z2
  ];
}

function line3(ctx,path,w,h,rng,stroke,width,alpha=1){
  if(!path || path.length<2) return;
  ctx.beginPath();

  path.forEach((p,i)=>{
    const q=project(p,w,h,rng);
    if(i===0) ctx.moveTo(q[0],q[1]);
    else ctx.lineTo(q[0],q[1]);
  });

  ctx.globalAlpha=alpha;
  ctx.strokeStyle=stroke;
  ctx.lineWidth=width;
  ctx.stroke();
  ctx.globalAlpha=1;
}

function draw3d(){
  const c=$("#view3d");
  const {ctx,w,h}=resizeCanvas(c);

  ctx.clearRect(0,0,w,h);

  if(!DATA){
    ctx.fillStyle="#8196a9";
    ctx.fillText("Uruchom analizę detekcji.",20,30);
    return;
  }

  const axis=DATA.geometry.axis_km;

  const pts=[];
  pts.push([0,0,0]);
  pts.push(DATA.geometry.graves);
  pts.push(DATA.geometry.station);

  const trajectoryAllowed=
    !DATA.quality ||
    DATA.quality.trajectory_allowed;

  if(trajectoryAllowed){

    for(const p of DATA.best.path)
      pts.push(p);

    for(const t of DATA.alternatives.slice(0,35)){
      for(const p of t.path)
        pts.push(p);
    }
  }

  let xmin=Infinity,xmax=-Infinity;
  let ymin=Infinity,ymax=-Infinity;
  let zmin=0,zmax=130;

  for(const p of pts){
    xmin=Math.min(xmin,p[0]);
    xmax=Math.max(xmax,p[0]);
    ymin=Math.min(ymin,p[1]);
    ymax=Math.max(ymax,p[1]);
    zmax=Math.max(zmax,p[2]);
  }

  const span=Math.max(xmax-xmin,ymax-ymin,zmax-zmin,1);

  const rng={
    cx:(xmin+xmax)/2,
    cy:(ymin+ymax)/2,
    cz:45,
    s:span
  };

  // grid XY
  ctx.strokeStyle="#172838";
  ctx.lineWidth=1;

  for(let i=0;i<=8;i++){
    const v=axis*i/8;

    line3(ctx,
      [[0,v,0],[axis,v,0]],
      w,h,rng,"#172838",1,.7);

    line3(ctx,
      [[v,0,0],[v,axis,0]],
      w,h,rng,"#172838",1,.7);
  }

  // axes
  line3(ctx,[[0,0,0],[axis*1.12,0,0]],w,h,rng,"#63798c",2,1);
  line3(ctx,[[0,0,0],[0,axis*1.12,0]],w,h,rng,"#63798c",2,1);
  line3(ctx,[[0,0,0],[0,0,140]],w,h,rng,"#63798c",2,1);

  if(trajectoryAllowed){

    // alternative trajectories
    for(const t of DATA.alternatives.slice(0,45)){
      line3(
        ctx,
        t.path,
        w,
        h,
        rng,
        "#aeb9c3",
        1,
        .12
      );
    }

    // best
    const bestColor=
      (
        DATA.quality &&
        DATA.quality.solution_mode==="FAMILY_ONLY"
      )
      ? "#ff9d2e"
      : "#ff4343";

    line3(
      ctx,
      DATA.best.path,
      w,
      h,
      rng,
      bestColor,
      3,
      1
    );

  }

  const g=project(DATA.geometry.graves,w,h,rng);
  const s=project(DATA.geometry.station,w,h,rng);

  ctx.fillStyle="#2e91ff";
  ctx.beginPath();
  ctx.arc(g[0],g[1],7,0,Math.PI*2);
  ctx.fill();

  ctx.fillStyle="#53d273";
  ctx.beginPath();
  ctx.arc(s[0],s[1],7,0,Math.PI*2);
  ctx.fill();

  ctx.font="12px system-ui";

  ctx.fillStyle="#dbe8f1";
  ctx.fillText("GRAVES — koniec osi X",g[0]+10,g[1]-7);
  ctx.fillText("Twoja stacja — koniec osi Y",s[0]+10,s[1]-7);

  const zx=project([0,0,140],w,h,rng);
  ctx.fillText("Z — wysokość [km]",zx[0]+7,zx[1]);

  ctx.fillText("X → GRAVES",20,h-28);
  ctx.fillText("Y → TWOJA STACJA",20,h-11);

  if(
    trajectoryAllowed
    &&
    DATA.quality
    &&
    DATA.quality.solution_mode==="FAMILY_ONLY"
  ){

    ctx.save();

    ctx.fillStyle="rgba(8,16,25,.80)";
    ctx.fillRect(
      w/2-225,
      18,
      450,
      54
    );

    ctx.strokeStyle="#a56d25";
    ctx.strokeRect(
      w/2-225,
      18,
      450,
      54
    );

    ctx.textAlign="center";

    ctx.fillStyle="#ffbd61";
    ctx.font="bold 14px system-ui";

    ctx.fillText(
      "FAMILY ONLY — geometria 3D niejednoznaczna",
      w/2,
      40
    );

    ctx.fillStyle="#b8c7d2";
    ctx.font="11px system-ui";

    ctx.fillText(
      "Linie przedstawiają równoważne rozwiązania Dopplera.",
      w/2,
      59
    );

    ctx.restore();
  }


  if(!trajectoryAllowed){

    const q=DATA.quality || {};

    ctx.save();

    ctx.fillStyle="rgba(8,16,25,.84)";
    ctx.fillRect(
      w/2-245,
      h/2-45,
      490,
      90
    );

    ctx.strokeStyle="#8b6630";
    ctx.lineWidth=1.5;

    ctx.strokeRect(
      w/2-245,
      h/2-45,
      490,
      90
    );

    ctx.textAlign="center";

    ctx.fillStyle="#ffd36d";
    ctx.font="bold 17px system-ui";

    ctx.fillText(
      q.echo_class || "TRAJECTORY BLOCKED",
      w/2,
      h/2-13
    );

    ctx.fillStyle="#d6e0e8";
    ctx.font="13px system-ui";

    ctx.fillText(
      "Trajektoria bryły 3D nie jest wyświetlana dla tego typu echa.",
      w/2,
      h/2+13
    );

    ctx.fillStyle="#8fa3b4";
    ctx.font="11px system-ui";

    ctx.fillText(
      "Waterfall i ridge pozostają prawidłowym wynikiem analizy sygnału.",
      w/2,
      h/2+34
    );

    ctx.restore();
  }
}

function waterfallColor(v){
  v=Math.max(0,Math.min(1,v));

  let r,g,b;

  if(v<0.25){
    const q=v/0.25;
    r=8+35*q;
    g=5+5*q;
    b=28+70*q;
  }
  else if(v<0.50){
    const q=(v-0.25)/0.25;
    r=43+100*q;
    g=10+15*q;
    b=98+45*q;
  }
  else if(v<0.75){
    const q=(v-0.50)/0.25;
    r=143+90*q;
    g=25+55*q;
    b=143-80*q;
  }
  else{
    const q=(v-0.75)/0.25;
    r=233+22*q;
    g=80+170*q;
    b=63+160*q;
  }

  return [
    Math.round(r),
    Math.round(g),
    Math.round(b)
  ];
}


function drawWaterfall(){

  const c=$("#waterfall");
  const {ctx,w,h}=resizeCanvas(c);

  ctx.clearRect(0,0,w,h);

  if(!SPEC){
    ctx.fillStyle="#8196a9";
    ctx.fillText(
      "Spektrogram pojawi się po analizie detekcji.",
      20,
      30
    );
    return;
  }

  const time=SPEC.time_s || [];
  const freq=SPEC.freq_hz || [];
  const z=SPEC.z || [];

  if(
    !time.length ||
    !freq.length ||
    !z.length
  ){
    ctx.fillStyle="#ff9d2e";
    ctx.fillText(
      "Brak danych waterfall.",
      20,
      30
    );
    return;
  }

  const nt=time.length;
  const nf=freq.length;

  const off=document.createElement("canvas");
  off.width=nt;
  off.height=nf;

  const oc=off.getContext("2d");
  const img=oc.createImageData(nt,nf);

  let zmin=Number(SPEC.z_floor);
  let zmax=Number(SPEC.z_ceil);

  if(!Number.isFinite(zmin)) zmin=0;
  if(!Number.isFinite(zmax) || zmax<=zmin) zmax=zmin+1;

  for(let ti=0;ti<nt;ti++){

    const row=z[ti];

    if(!row) continue;

    for(let fi=0;fi<nf;fi++){

      const val=Number(row[fi]);

      let q=(val-zmin)/(zmax-zmin);

      q=Math.max(
        0,
        Math.min(1,q)
      );

      // freq dodatni na górze
      const yy=nf-1-fi;

      const pos=(
        yy*nt + ti
      )*4;

      const rgb=waterfallColor(q);

      img.data[pos+0]=rgb[0];
      img.data[pos+1]=rgb[1];
      img.data[pos+2]=rgb[2];
      img.data[pos+3]=255;
    }
  }

  oc.putImageData(img,0,0);

  const L=55;
  const R=18;
  const T=15;
  const B=32;

  const PW=w-L-R;
  const PH=h-T-B;

  ctx.imageSmoothingEnabled=true;

  ctx.drawImage(
    off,
    L,
    T,
    PW,
    PH
  );

  const tmin=Number(time[0]);
  const tmax=Number(time[time.length-1]);

  const fmin=Math.min(...freq);
  const fmax=Math.max(...freq);

  const X=t =>
    L+
    (t-tmin)/(tmax-tmin || 1)*PW;

  const Y=f =>
    T+
    (fmax-f)/(fmax-fmin || 1)*PH;


  // ----------------------------------------------------------
  // 0 Hz
  // ----------------------------------------------------------

  if(fmin<=0 && fmax>=0){

    ctx.strokeStyle="rgba(210,225,235,.65)";
    ctx.lineWidth=1;
    ctx.setLineDash([6,5]);

    ctx.beginPath();
    ctx.moveTo(L,Y(0));
    ctx.lineTo(w-R,Y(0));
    ctx.stroke();

    ctx.setLineDash([]);

    ctx.fillStyle="#c4d2dc";
    ctx.font="11px system-ui";
    ctx.fillText(
      "0 Hz",
      8,
      Y(0)+4
    );
  }


  // ----------------------------------------------------------
  // TRIGGER
  // ----------------------------------------------------------

  const trig=
    SPEC.meta &&
    Number(SPEC.meta.trigger_offset_s);

  if(Number.isFinite(trig)){

    const tx=X(trig);

    ctx.strokeStyle="#e7c75f";
    ctx.lineWidth=1.5;
    ctx.setLineDash([5,4]);

    ctx.beginPath();
    ctx.moveTo(tx,T);
    ctx.lineTo(tx,T+PH);
    ctx.stroke();

    ctx.setLineDash([]);

    ctx.fillStyle="#e7c75f";
    ctx.font="11px system-ui";

    ctx.fillText(
      "trigger",
      Math.min(tx+4,w-58),
      T+13
    );
  }


  // ----------------------------------------------------------
  // FULL RIDGE — cały wykryty sygnał
  // ----------------------------------------------------------

  if(
    DATA &&
    DATA.signal &&
    DATA.signal.full_ridge &&
    DATA.signal.full_ridge.time_s &&
    DATA.signal.full_ridge.freq_hz
  ){

    const ft=
      DATA.signal.full_ridge.time_s;

    const ff=
      DATA.signal.full_ridge.freq_hz;


    if(ft.length){

      ctx.strokeStyle=
        "rgba(255,157,46,.85)";

      ctx.lineWidth=2.0;

      ctx.shadowColor="#000";
      ctx.shadowBlur=2;

      ctx.beginPath();

      for(let i=0;i<ft.length;i++){

        const x=X(ft[i]);
        const y=Y(ff[i]);

        if(i===0)
          ctx.moveTo(x,y);
        else
          ctx.lineTo(x,y);
      }

      ctx.stroke();

      ctx.shadowBlur=0;
    }
  }


  // ----------------------------------------------------------
  // RIDGE UŻYWANY PRZEZ SOLVER 3D
  // ----------------------------------------------------------

  if(
    DATA &&
    DATA.signal &&
    DATA.signal.trajectory_ridge &&
    DATA.signal.trajectory_ridge.time_s &&
    DATA.signal.trajectory_ridge.freq_hz
  ){

    const rt=
      DATA.signal.trajectory_ridge.time_s;

    const rf=
      DATA.signal.trajectory_ridge.freq_hz;

    ctx.strokeStyle="#ff3030";
    ctx.lineWidth=3.2;
    ctx.shadowColor="#000";
    ctx.shadowBlur=4;

    ctx.beginPath();

    for(let i=0;i<rt.length;i++){

      const x=X(rt[i]);
      const y=Y(rf[i]);

      if(i===0)
        ctx.moveTo(x,y);
      else
        ctx.lineTo(x,y);
    }

    ctx.stroke();

    ctx.shadowBlur=0;


    // punkty początku / końca

    if(rt.length){

      const sx=X(rt[0]);
      const sy=Y(rf[0]);

      const ex=X(rt[rt.length-1]);
      const ey=Y(rf[rf.length-1]);

      ctx.fillStyle="#42ff78";

      ctx.beginPath();
      ctx.arc(sx,sy,5,0,Math.PI*2);
      ctx.fill();

      ctx.fillStyle="#ffcc36";

      ctx.beginPath();
      ctx.arc(ex,ey,5,0,Math.PI*2);
      ctx.fill();


      ctx.font="bold 11px system-ui";

      ctx.fillStyle="#42ff78";
      ctx.fillText(
        "START",
        sx+7,
        sy-6
      );

      ctx.fillStyle="#ffcc36";
      ctx.fillText(
        "KONIEC",
        ex+7,
        ey+14
      );
    }
  }


  // ----------------------------------------------------------
  // RAMKA
  // ----------------------------------------------------------

  ctx.strokeStyle="#425567";
  ctx.lineWidth=1;

  ctx.strokeRect(
    L,
    T,
    PW,
    PH
  );


  // ----------------------------------------------------------
  // OPISY OSI
  // ----------------------------------------------------------

  ctx.fillStyle="#a7bac8";
  ctx.font="11px system-ui";

  ctx.fillText(
    Math.round(fmax)+" Hz",
    5,
    T+9
  );

  ctx.fillText(
    Math.round(fmin)+" Hz",
    5,
    T+PH
  );

  ctx.fillText(
    tmin.toFixed(2)+" s",
    L,
    h-9
  );

  const endText=tmax.toFixed(2)+" s";

  ctx.fillText(
    endText,
    w-R-40,
    h-9
  );

  ctx.fillText(
    "czas →",
    w/2-18,
    h-9
  );
}


function drawDoppler(){
  const c=$("#doppler");
  const {ctx,w,h}=resizeCanvas(c);

  ctx.clearRect(0,0,w,h);

  if(!DATA) return;

  const t=DATA.doppler.time_s;
  const obs=DATA.doppler.observed_hz;
  const mod=DATA.doppler.model_hz;

  const xmin=Math.min(...t);
  const xmax=Math.max(...t);

  let ymin=Math.min(...obs,...mod,0);
  let ymax=Math.max(...obs,...mod,0);

  const pad=(ymax-ymin)*.12||10;
  ymin-=pad;
  ymax+=pad;

  const L=55,R=18,T=15,B=33;

  const X=x=>L+(x-xmin)/(xmax-xmin||1)*(w-L-R);
  const Y=y=>T+(ymax-y)/(ymax-ymin||1)*(h-T-B);

  ctx.strokeStyle="#213648";
  ctx.lineWidth=1;

  for(let i=0;i<=5;i++){
    const yy=T+(h-T-B)*i/5;
    ctx.beginPath();
    ctx.moveTo(L,yy);
    ctx.lineTo(w-R,yy);
    ctx.stroke();
  }

  if(ymin<0 && ymax>0){
    ctx.strokeStyle="#788b9a";
    ctx.setLineDash([5,5]);
    ctx.beginPath();
    ctx.moveTo(L,Y(0));
    ctx.lineTo(w-R,Y(0));
    ctx.stroke();
    ctx.setLineDash([]);
  }

  function series(a,color,width){
    ctx.strokeStyle=color;
    ctx.lineWidth=width;
    ctx.beginPath();

    a.forEach((v,i)=>{
      const x=X(t[i]),y=Y(v);
      if(!i) ctx.moveTo(x,y);
      else ctx.lineTo(x,y);
    });

    ctx.stroke();
  }

  series(obs,"#ff9d2e",2.5);
  series(mod,"#2e91ff",2);

  ctx.fillStyle="#a7bac8";
  ctx.font="11px system-ui";
  ctx.fillText("Doppler [Hz]",8,17);
  ctx.fillText("czas [s]",w-56,h-10);

  ctx.fillStyle="#ff9d2e";
  ctx.fillText("pomiar",L+8,20);

  ctx.fillStyle="#2e91ff";
  ctx.fillText("model",L+70,20);
}

function metric(name,value){
  return `<div class="metric"><span>${name}</span><span>${value}</span></div>`;
}


function kinNum(v,d=2){
  const n=Number(v);
  return Number.isFinite(n) ? n.toFixed(d) : "—";
}

function fillKinematics(){
  const el=$("#kinematics");

  if(!el)
    return;

  const k=
    DATA &&
    DATA.kinematics_evidence
      ? DATA.kinematics_evidence
      : null;

  if(!k){
    el.className="kinematics kin-none";
    el.innerHTML=
      `<div class="kin-head">
         <span>Doppler curvature / kinematics evidence</span>
         <span class="kin-badge">—</span>
       </div>
       <div class="kin-note">
         Brak danych kinematycznych.
       </div>`;
    return;
  }

  const level=
    String(
      k.evidence_level || "NONE"
    ).toUpperCase();

  let cls="kin-none";

  if(level==="STRONG")
    cls="kin-strong";
  else if(level==="MODERATE")
    cls="kin-moderate";
  else if(level==="EXPLORATORY")
    cls="kin-exploratory";
  else if(level==="WEAK")
    cls="kin-weak";
  else if(level==="BLOCKED")
    cls="kin-blocked";

  el.className=
    "kinematics "+cls;

  if(!k.valid){

    el.innerHTML=
      `<div class="kin-head">
         <span>Doppler curvature / kinematics evidence</span>
         <span class="kin-badge">${level}</span>
       </div>
       <div class="kin-note">
         ${k.message || k.reason || "Brak wyniku."}
       </div>`;

    return;
  }

  const input=
    k.phase_used
      ? "RAW IQ phase"
      : "FFT ridge";

  const support=
    String(
      k.shape_support || "NONE"
    ).toUpperCase();

  const blocks=
    `${k.blocks_better ?? 0}/${k.blocks_total ?? 0}`;

  const curvature=
    `${kinNum(k.curvature_hz_s2,1)} Hz/s²`;

  const dbic=
    kinNum(
      k.delta_bic_eff,
      2
    );

  const neff=
    `${kinNum(k.n_eff,1)} / ${k.n_points ?? "—"}`;

  const gain=
    `${kinNum(k.rmse_gain_hz,2)} Hz`;

  const direction=
    String(
      k.curvature_direction || "—"
    );

  el.innerHTML=
    `<div class="kin-head">
       <span>Doppler curvature / kinematics evidence</span>
       <span class="kin-badge">${level}</span>
     </div>

     <div class="kin-grid">

       <div class="kin-item">
         <span>Wejście</span>
         ${input}
       </div>

       <div class="kin-item">
         <span>Shape support</span>
         ${support}
       </div>

       <div class="kin-item">
         <span>ΔBIC eff.</span>
         ${dbic}
       </div>

       <div class="kin-item">
         <span>N eff. / N</span>
         ${neff}
       </div>

       <div class="kin-item">
         <span>Bloki quadratic lepsze</span>
         ${blocks}
       </div>

       <div class="kin-item">
         <span>RMSE gain</span>
         ${gain}
       </div>

       <div class="kin-item">
         <span>Krzywizna f″</span>
         ${curvature}
       </div>

       <div class="kin-item">
         <span>Znak krzywizny</span>
         ${direction}
       </div>

     </div>

     <div class="kin-note">
       ${k.message || ""}
       <br>
       <b>To cecha kształtu Dopplera, nie bezpośredni
       pomiar fizycznego przyspieszenia meteoroidu.</b>
     </div>`;
}

function fillMetrics(){
  fillKinematics();


  if(!DATA) return;

  const b=DATA.best;
  const q=DATA.quality || {};

  const score=Number(
    q.confidence_score ?? 0
  );

  let qclass="quality-low";

  if(q.confidence_label==="MODERATE")
    qclass="quality-moderate";

  else if(q.confidence_label==="LIMITED")
    qclass="quality-limited";


  const hits=
    Array.isArray(q.boundary_hits)
      ? q.boundary_hits
      : [];

  const ensemble=DATA.ensemble || {};

  const solutionMode=
    q.solution_mode ||
    (
      q.trajectory_allowed
        ? "BEST_PLUS_FAMILY"
        : "BLOCKED"
    );

  const issues=
    Array.isArray(q.issues)
      ? q.issues
      : [];


  $("#quality").className=
    "quality "+qclass;


  $("#quality").innerHTML=
    `<div class="quality-title">
       ${q.echo_label || "BRAK KLASYFIKACJI"}
     </div>

     <div class="quality-score">
       ${q.confidence_label || "LOW"}
       • ${score}/100
     </div>

     <div>
       3D:
       <b>
       ${
         solutionMode==="FAMILY_ONLY"
           ? "RODZINA ROZWIĄZAŃ"
           :
           (
             q.trajectory_allowed
               ? "AKTYWNY"
               : "ZABLOKOWANY"
           )
       }
       </b>
     </div>

     ${
       (
         DATA.signal &&
         DATA.signal.segmentation &&
         DATA.signal.segmentation.detected
       )
       ?
       `<div style="margin-top:7px;color:#ffbd61">
          Solver 3D: tylko dynamiczny początek
        </div>`
       :
       ""
     }

     ${
       hits.length
       ? `<div style="margin-top:7px">
            Granice solvera:<br>
            ${hits.join("<br>")}
          </div>`
       : ""
     }

     ${
       issues.length
       ? `<div style="margin-top:7px">
            ${issues.join("<br>")}
          </div>`
       : ""
     }

     <div class="quality-note">
       Score jest wskaźnikiem heurystycznym,
       nie prawdopodobieństwem.
       Dla jednej stacji maksimum = 65/100.
     </div>`;


  let html="";

  html +=
    metric(
      "Typ echa",
      q.echo_class || "—"
    );


  const seg=
    (
      DATA.signal &&
      DATA.signal.segmentation
    )
    ? DATA.signal.segmentation
    : {};


  const phase=
    (
      DATA.signal &&
      DATA.signal.phase_tracking
    )
    ? DATA.signal.phase_tracking
    : {};


  html += metric(
    "Źródło Dopplera",
    phase.used
      ? "RAW IQ PHASE • 5 ms"
      : "FFT RIDGE"
  );


  if(phase.attempted){

    html += metric(
      "Phase tracking",
      phase.used
        ? "AKTYWNY"
        : "FALLBACK FFT"
    );

    if(
      phase.snr_db !== undefined
    ){
      html += metric(
        "Phase SNR",
        Number(
          phase.snr_db
        ).toFixed(1)+" dB"
      );
    }

    if(
      phase.phase_points !== undefined
    ){
      html += metric(
        "Punkty fazowe",
        phase.phase_points
      );
    }

    if(
      phase.correction_p90_abs_hz !== undefined
    ){
      html += metric(
        "Phase Δ P90",
        Number(
          phase.correction_p90_abs_hz
        ).toFixed(1)+" Hz"
      );
    }
  }


  if(seg.detected){

    html += metric(
      "Komponent użyty do 3D",
      "DYNAMIC HEAD ONLY"
    );

    html += metric(
      "Dynamiczny początek",
      Number(
        seg.head_duration_s || 0
      ).toFixed(3)+" s"
    );

    html += metric(
      "Punkty dynamic head",
      (
        seg.head_full_points ?? "—"
      )
      +
      " / solver "
      +
      (
        seg.solver_input_points
        ??
        seg.head_solver_points
        ??
        "—"
      )
    );

    html += metric(
      "Pełny ridge — punkty",
      seg.full_ridge_points ?? "—"
    );

    html += metric(
      "Długi trail",
      Number(
        seg.tail_duration_s || 0
      ).toFixed(3)+" s"
    );

    html += metric(
      "Span początku",
      Number(
        seg.head_span_hz || 0
      ).toFixed(1)+" Hz"
    );
  }


  html +=
    metric(
      "Trajectory confidence",
      `${q.confidence_label || "LOW"} • ${score}/100`
    );

  html +=
    metric(
      "Geometry stability",
      q.trajectory_allowed
        ?
        `${q.geometry_stability_label || "—"} • ${
          q.geometry_stability_score ?? 0
        }/100`
        :
        "N/D — 3D zablokowane"
    );

  html +=
    metric(
      "3D",
      solutionMode==="FAMILY_ONLY"
        ? "RODZINA ROZWIĄZAŃ"
        :
        (
          q.trajectory_allowed
            ? "AKTYWNY"
            : "ZABLOKOWANY"
        )
    );

  html +=
    metric(
      "RMSE",
      b.rmse_hz.toFixed(1)+" Hz"
    );

  html +=
    metric(
      "Offset Dopplera",
      b.doppler_bias_hz.toFixed(1)+" Hz"
    );


  if(
    q.trajectory_allowed
    &&
    solutionMode!=="FAMILY_ONLY"
  ){

    html +=
      metric(
        "Wysokość początku",
        b.start_alt_km.toFixed(1)+" km"
      );

    html +=
      metric(
        "Wysokość środka",
        b.altitude_mid_km.toFixed(1)+" km"
      );

    html +=
      metric(
        "Wysokość końca",
        b.end_alt_km.toFixed(1)+" km"
      );

    html +=
      metric(
        "Prędkość modelowa — środek",
        b.speed_kms.toFixed(1)+" km/s"
      );

    html +=
      metric(
        "Prędkość start",
        Number(
          b.speed_start_kms
        ).toFixed(1)+" km/s"
      );

    html +=
      metric(
        "Prędkość koniec",
        Number(
          b.speed_end_kms
        ).toFixed(1)+" km/s"
      );

    html +=
      metric(
        "a∥ modelu 3D (zależne od geometrii)",
        Number(
          b.along_track_accel_kms2
        ).toFixed(2)+" km/s²"
      );

    html +=
      metric(
        "Interpretacja a∥",
        Number(
          b.along_track_accel_kms2
        ) < 0
          ? "DECELERACJA"
          : "PRZYSPIESZANIE"
      );

    html +=
      metric(
        "Azymut modelowy",
        b.azimuth_deg.toFixed(1)+"°"
      );

    html +=
      metric(
        "Kąt zejścia",
        b.down_angle_deg.toFixed(1)+"°"
      );

  }
  else if(
    q.trajectory_allowed
    &&
    solutionMode==="FAMILY_ONLY"
  ){

    const ar=
      ensemble.altitude_mid_km_p10_p90 || [];

    const sr=
      ensemble.speed_kms_p10_p90 || [];

    const dr=
      ensemble.down_angle_deg_p10_p90 || [];

    const acr=
      ensemble.along_track_accel_kms2_p10_p90 || [];


    if(ar.length===2){

      html += metric(
        "Wysokość środka — zakres",
        ar[0].toFixed(1)+
        "–"+
        ar[1].toFixed(1)+
        " km"
      );
    }


    if(sr.length===2){

      html += metric(
        "Prędkość — zakres",
        sr[0].toFixed(1)+
        "–"+
        sr[1].toFixed(1)+
        " km/s"
      );
    }


    if(dr.length===2){

      html += metric(
        "Kąt zejścia — zakres",
        dr[0].toFixed(1)+
        "–"+
        dr[1].toFixed(1)+
        "°"
      );
    }


    if(acr.length===2){

      html += metric(
        "a∥ — zakres",
        acr[0].toFixed(1)+
        "–"+
        acr[1].toFixed(1)+
        " km/s²"
      );
    }

    html += metric(
      "Rozrzut azymutu",
      Number(
        ensemble.azimuth_max_delta_deg || 0
      ).toFixed(1)+"°"
    );

    html += metric(
      "Równoważne rozwiązania",
      ensemble.near_best_solutions || 0
    );

  }
  else{

    html +=
      metric(
        "Parametry lotu 3D",
        "UKRYTE"
      );
  }


  html +=
    metric(
      "GRAVES ↔ stacja",
      DATA.baseline_km.toFixed(1)+" km"
    );

  html +=
    metric(
      "Monte Carlo",
      DATA.monte_carlo.toLocaleString("pl-PL")
    );

  html +=
    metric(
      "Punkty Dopplera",
      DATA.ridge.points
    );

  html +=
    metric(
      "Czas śladu",
      (
        DATA.doppler.time_s[
          DATA.doppler.time_s.length-1
        ]
        -
        DATA.doppler.time_s[0]
      ).toFixed(3)+" s"
    );

  html +=
    metric(
      "Doppler span",
      (
        Math.max(...DATA.doppler.observed_hz)
        -
        Math.min(...DATA.doppler.observed_hz)
      ).toFixed(1)+" Hz"
    );

  html +=
    metric(
      "Doppler start",
      DATA.doppler.observed_hz[0].toFixed(1)+" Hz"
    );

  html +=
    metric(
      "Doppler koniec",
      DATA.doppler.observed_hz[
        DATA.doppler.observed_hz.length-1
      ].toFixed(1)+" Hz"
    );

  html +=
    metric(
      "FFT bin",
      DATA.ridge.bin_hz.toFixed(2)+" Hz"
    );


  $("#metrics").innerHTML=html;

  $("#warning").textContent=
    DATA.warning;


  $("#ridge").textContent=
    "Ślad: "+
    DATA.ridge.points+
    " pkt • "+
    (q.echo_class || "—")+
    " • Doppler: "+
    (
      DATA.ridge.doppler_source ||
      "FFT_RIDGE"
    );
}


async function run(){
  const file=$("#event").value;
  const mc=$("#mc").value;

  if(!file) return;

  $("#run").disabled=true;
  $("#message").textContent="Liczenie trajektorii…";

  const start=performance.now();

  try{
    const u=
      "/api/analyze?file="+
      encodeURIComponent(file)+
      "&mc="+mc;

    const r=await fetch(u);
    const j=await r.json();

    if(!r.ok || j.error){
      throw new Error(j.error||("HTTP "+r.status));
    }

    DATA=j;

    try{
      const su=
        "/api/spectrogram?file="+
        encodeURIComponent(file)+
        "&span=300&fft=4096";

      const sr=await fetch(su);
      SPEC=await sr.json();

      if(!sr.ok || SPEC.error){
        console.warn(
          "Waterfall:",
          SPEC.error || ("HTTP "+sr.status)
        );
        SPEC=null;
      }
    }
    catch(e){
      console.warn(
        "Nie udało się pobrać waterfall:",
        e
      );
      SPEC=null;
    }

    fillMetrics();
    draw3d();
    drawWaterfall();
    drawDoppler();

    const sec=(performance.now()-start)/1000;

    $("#calc").textContent=
      "Obliczenia: "+sec.toFixed(1)+" s";

    $("#message").textContent="Gotowe";
  }
  catch(e){
    console.error(e);
    $("#message").textContent="BŁĄD: "+e.message;
  }
  finally{
    $("#run").disabled=false;
  }
}

$("#run").onclick=run;

const cv=$("#view3d");

cv.addEventListener("mousedown",e=>{
  dragging=true;
  px=e.clientX;
  py=e.clientY;
});

window.addEventListener("mouseup",()=>dragging=false);

window.addEventListener("mousemove",e=>{
  if(!dragging) return;

  const dx=e.clientX-px;
  const dy=e.clientY-py;

  if(e.shiftKey){
    panX += dx;
    panY += dy;
  }else{
    yaw += dx*0.008;
    pitch += dy*0.006;

    pitch=Math.max(-1.25,Math.min(1.25,pitch));
  }

  px=e.clientX;
  py=e.clientY;

  draw3d();
});

cv.addEventListener("wheel",e=>{
  e.preventDefault();

  const factor = e.deltaY < 0 ? 1.16 : 1/1.16;

  zoom3d *= factor;
  zoom3d = Math.max(0.45,Math.min(12.0,zoom3d));

  draw3d();
},{
  passive:false
});

cv.addEventListener("dblclick",()=>{
  yaw=-0.72;
  pitch=0.52;
  zoom3d=1.0;
  panX=0;
  panY=0;
  draw3d();
});

window.addEventListener("resize",()=>{
  draw3d();
  drawWaterfall();
  drawDoppler();
});

loadEvents().catch(e=>{
  $("#message").textContent="Błąd listy detekcji: "+e;
});

draw3d();
</script>
</body>
</html>
'''


class Handler(BaseHTTPRequestHandler):

    def reply(self, status, content_type, body):
        if isinstance(body, str):
            body = body.encode("utf-8")

        self.send_response(status)
        self.send_header(
            "Content-Type",
            content_type
        )
        self.send_header(
            "Content-Length",
            str(len(body))
        )
        self.send_header(
            "Cache-Control",
            "no-store"
        )
        self.end_headers()
        self.wfile.write(body)

    def json_reply(self, obj, status=200):
        self.reply(
            status,
            "application/json; charset=utf-8",
            json.dumps(
                obj,
                ensure_ascii=False,
                separators=(",", ":")
            )
        )

    def do_GET(self):
        try:
            u = urllib.parse.urlparse(
                self.path
            )

            q = urllib.parse.parse_qs(
                u.query
            )

            if u.path == "/":
                self.reply(
                    200,
                    "text/html; charset=utf-8",
                    INDEX
                )
                return

            if u.path == "/healthz":
                upstream_ok = False

                try:
                    urllib.request.urlopen(
                        UPSTREAM+"/healthz",
                        timeout=2
                    ).read()

                    upstream_ok = True

                except Exception:
                    pass

                self.json_reply({
                    "ok": True,
                    "service":
                        "meteorradio-trajectory",

                    "version":
                        "1.0",

                    "port":
                        PORT,

                    "upstream_8099":
                        upstream_ok,

                    "baseline_km":
                        BASELINE_KM,

                    "numpy":
                        np.__version__,
                })
                return

            if u.path == "/api/events":
                data = upstream_json(
                    "/api/events?limit=120"
                )

                self.json_reply(
                    data
                )
                return

            if u.path == "/api/spectrogram":

                filename = q.get(
                    "file",
                    [""]
                )[0]

                if (
                    not filename
                    or Path(filename).name != filename
                    or not filename.endswith(".npz")
                ):
                    self.json_reply(
                        {"error":"Nieprawidłowa nazwa NPZ"},
                        400
                    )
                    return

                span = q.get(
                    "span",
                    ["300"]
                )[0]

                fft = q.get(
                    "fft",
                    ["4096"]
                )[0]

                query = urllib.parse.urlencode({
                    "file": filename,
                    "span": span,
                    "fft": fft,
                })

                data = upstream_json(
                    "/api/spectrogram?"
                    + query
                )

                self.json_reply(data)
                return


            if u.path == "/api/analyze":
                filename = q.get(
                    "file",
                    [""]
                )[0]

                mc = int(
                    q.get(
                        "mc",
                        ["8000"]
                    )[0]
                )

                data = analyze(
                    filename,
                    mc
                )

                self.json_reply(
                    data
                )
                return

            self.json_reply(
                {"error": "not found"},
                404
            )

        except Exception as e:
            traceback.print_exc()

            self.json_reply(
                {
                    "error": str(e),
                    "type":
                        type(e).__name__,
                },
                500
            )

    def log_message(self, fmt, *args):
        print(
            "%s - %s"
            % (
                self.address_string(),
                fmt % args
            ),
            flush=True
        )


if __name__ == "__main__":
    server = ThreadingHTTPServer(
        ("0.0.0.0", PORT),
        Handler
    )

    print(
        "MeteorRadio 3D Trajectory Analyzer v0.8",
        flush=True
    )

    print(
        "PORT:",
        PORT,
        flush=True
    )

    print(
        "GRAVES ↔ RX:",
        f"{BASELINE_KM:.1f} km",
        flush=True
    )

    server.serve_forever()
