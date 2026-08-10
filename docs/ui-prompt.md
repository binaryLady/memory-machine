# Prompt: add `/memorymachine` telemetry + logging UI

Add a new route to the existing TheTechMargin app at:

```
https://lab.thetechmargin.com/memorymachine
```

The page receives telemetry from the `memory-machine` Raspberry Pi installation
and lets us monitor it remotely.

## Backend endpoint

Expose a single POST endpoint at:

```
POST https://lab.thetechmargin.com/memorymachine/api/telemetry
Content-Type: application/json
```

The body is a JSON array of telemetry records. Each record has:

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
  frames_preloaded?: boolean;
  last_error?: string;
  log_tail?: string[]; // last N lines of the local log file
}
```

Store the latest record (or the latest per-installation if you later add an
installation ID) in memory or a small persistent store. The Pi currently sends
telemetry from a single device, so a single global latest-state bucket is fine.

## Frontend page

At `lab.thetechmargin.com/memorymachine` render:

1. **Live status card** — online/offline (heartbeat within last 2× interval),
   current state (`IDLE` / `ENGAGED`), sensor name, raw sensor reading.
2. **Counts** — lift, accepted transitions, rejected transitions, uptime.
3. **Audio/video health** — resolved audio sink, frames preloaded, last error.
4. **Event feed** — most recent lift/replace events with timestamps; show in
   chronological order newest-first.
5. **Log tail viewer** — render the `log_tail` array as a monospace, read-only
   log window. Auto-scroll to the bottom on new heartbeats.

## Design requirements

- Use the existing TTM stack (TypeScript, React).
- No default exports from components; use `export function ComponentName`.
- No `any` without an explicit disable comment and reason.
- Pull all colors from the project’s CSS variables / design tokens; no hardcoded
  hex values.
- Keep the page responsive down to mobile widths.
- Add a short label and accessible controls (tooltips as verb phrases, no
  icon-only buttons without labels).
- Page title: “memory-machine monitor — The Tech Margin”.

## Optional / future

- Accept an installation ID from the Pi later so multiple gallery pieces can be
  monitored on one page.
- Add a simple Bearer-token gate if the route needs protection.

## References

- Engine repo: https://github.com/binaryLady/memory-machine
- Telemetry sender: `src/telemetry.py`
- Config section: `[telemetry]` in `config/config.default.ini`
