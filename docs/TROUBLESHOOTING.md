# Troubleshooting

## RTL-SDR cannot open

Check:

```bash
rtl_test
lsusb
ps aux | grep -Ei 'rtl|satnogs|radiosonde|meteor'
```

If the dongle is shared, check radio-owner state before killing anything.

## Panel does not open

Check listener and service:

```bash
sudo ss -ltnp | grep -E ':8094|:8095|:8096|:8097'
systemctl status meteorradio-web.service --no-pager
systemctl status meteorradio-likes.service --no-pager
systemctl status meteorradio-stats.service --no-pager
```

## New SMP is not scored yet

The score worker is timer-driven. Check:

```bash
systemctl status meteorradio-score-new.timer --no-pager
journalctl -u meteorradio-score-new.service -n 100 --no-pager
```

A very recent unscored SMP is not necessarily an error if it appeared between timer cycles.

## Cached image is stale

Check renderer/pre-render service and compare modification times of the SMP, renderer and cached PNG.

## Temperature/throttling

On Raspberry Pi:

```bash
vcgencmd measure_temp
vcgencmd get_throttled
```

A historical flag is different from a currently active throttling flag. Record both when reporting a problem.

## Python syntax after editing

```bash
python3 -m py_compile path/to/file.py
```

Always compile before restarting a service after manual edits.
