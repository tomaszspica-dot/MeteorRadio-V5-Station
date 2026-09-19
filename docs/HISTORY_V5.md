# V5 reference history

The V5 Golden was produced after a final audit and cleanup cycle.

Reference snapshot:

```text
20260919_023454_V5
```

Verification facts recorded at Golden creation:

- Golden source files: 69
- size: about 1.2 MB
- Python snapshot syntax check: passed
- critical live/copy hashes: matched
- local HTTP endpoints 8094–8097: passed
- persistent zombie gate: passed
- current throttling/undervoltage flags: clear at snapshot time
- score/likes/retention consistency: passed after cleanup
- final SHA-256 manifest verification: passed
- MeteorRadio acquisition process was not restarted during Golden creation

The Golden intentionally excluded raw SMP observations and generated PNG cache.
