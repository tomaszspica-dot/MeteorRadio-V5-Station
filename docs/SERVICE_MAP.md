# Service map

| Unit | Type | Reference state | Function |
|---|---|---|---|
| `meteorradio.service` | service | active when owner=METEOR; intentionally not boot-enabled in shared-radio reference | acquisition/detection |
| `meteorradio-web.service` | service | enabled | main UI on 8094 |
| `meteorradio-queue-status.service` | service | enabled | queue/status on 8095 |
| `meteorradio-likes.service` | service | enabled | favourites/retention on 8096 |
| `meteorradio-stats.service` | service | enabled | stats on 8097 |
| `meteorradio-prerender.service` | service | enabled | cache rendering |
| `meteorradio-score-new.service` | oneshot/static worker | timer-triggered | score new detections |
| `meteorradio-score-new.timer` | timer | enabled | launches scoring periodically |
| `meteorradio-retention.service` | oneshot/static worker | timer-triggered | retention cleanup |
| `meteorradio-retention.timer` | timer | enabled | launches retention cleanup |
| `meteorradio-healthcheck.service` | oneshot/static worker | timer-triggered | passive health snapshot |
| `meteorradio-healthcheck.timer` | timer | enabled | periodic health check |
| `radio-owner-restore.service` | service | enabled only for shared-radio design | restores persisted radio owner after boot |

## Important reference behavior

In the shared-radio reference build, `meteorradio.service` being `disabled` is deliberate. `radio-owner-restore.service` decides which receiver should own the RTL-SDR after boot.

Do not change that design without understanding the local radio-sharing topology.

---

## Final V5 analysis services

| Port | Service | Purpose |
|---:|---|---|
| 8094 | MeteorRadio web | Main detection interface |
| 8095 | Queue/status | Scoring queue status |
| 8096 | Likes/retention | Score/like/retention API |
| 8097 | Statistics | Detection statistics |
| 8099 | 3D Spectrogram Viewer | Read-only saved-observation analysis |
| 8100 | 3D Trajectory Analyzer | Single-station bistatic trajectory-family analysis |

The 8099/8100 analysis chain operates on saved observations and does not acquire the RTL-SDR directly.
