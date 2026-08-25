# Telemetry wire format

The engine's optional telemetry (see `[telemetry]` in
`config/config.default.ini`, off by default) POSTs to whatever endpoint you
configure. This is the format a receiving dashboard should expect.

## Endpoint

```
POST <endpoint_url>
Content-Type: application/json
```

The body is a JSON array of telemetry records, batched up to `batch_size`.

## Records

```ts
interface TelemetryRecord {
  type: "event" | "heartbeat";
  event?: "lift" | "replace" | "heartbeat";
  timestamp: string; // ISO-8601 UTC
  monotonic_s: number;
  // event fields
  source?: string;        // sensor name, e.g. "switch"
  state?: "IDLE" | "ENGAGED";
  monotonic_ts?: number;
  // heartbeat fields
  sensor?: string;
  sensor_engaged?: boolean;
  sensor_raw?: "engaged" | "idle" | null;
  uptime_s?: number;
  lift_count?: number;
  accepted_count?: number;
  rejected_count?: number;
  audio_sink?: string;
  last_error?: string;
  // compact health subset (present when available)
  cpu_percent?: number;
  temperature_c?: number;
  throttled?: string;
  fan_level?: number;
  asleep?: boolean;
  version?: string;
  fps?: number;
  target_fps?: number;
  frame_worst_ms?: number;
  // only when [system] mode = test; production keeps logs local
  log_tail?: string[];
}
```

An **event** record is sent for every accepted `lift` and `replace`. A
**heartbeat** is sent every `interval_s` seconds. Nothing else is transmitted:
no file paths, no user identifiers.

## Suggested dashboard

1. **Live status card** — online/offline (heartbeat within last 2× interval),
   current state (`IDLE` / `ENGAGED`), sensor name, raw sensor reading.
2. **Counts** — lift, accepted transitions, rejected transitions, uptime.
3. **Health** — CPU, temperature, throttle flags, playback fps, resolved audio
   sink, last error.
4. **Event feed** — most recent lift/replace events, newest first.
5. **Log tail viewer** — monospace read-only window for `log_tail`, when the
   piece runs in test mode.

The Pi sends telemetry from a single device, so a single latest-state bucket
is fine; accept an installation ID later if multiple pieces share one
dashboard. Protect the route (e.g. a Bearer token) if it is public.

## References

- Telemetry sender: `src/telemetry.py`
- Config section: `[telemetry]` in `config/config.default.ini`
