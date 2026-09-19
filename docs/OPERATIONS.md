# Operations

## Quick service status

```bash
systemctl --no-pager --type=service | grep -E 'meteorradio|radio-owner'
systemctl list-timers --all | grep -E 'meteorradio'
```

## Local panels

```text
http://<pi-host>:8094   main detections
http://<pi-host>:8095   scoring queue/status
http://<pi-host>:8096   favourites/retention
http://<pi-host>:8097   statistics
```

## HTTP health check

```bash
for p in 8094 8095 8096 8097; do
  curl -sS -o /dev/null -w "$p %{http_code}\n" "http://127.0.0.1:$p/"
done
```

## Shared-radio reference

Check owner status:

```bash
sudo /usr/local/sbin/radio-owner-control status
```

Do not start a second SDR consumer before confirming the first one has released the dongle.

## Raw data

Reference raw detections are stored under a `radar_data` directory. Raw SMP files can become large over time; retention and manual curation are therefore part of normal station operation.
