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
