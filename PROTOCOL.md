# VR Telemetry Hub — Plugin Protocol v1

> **Vendored copy.** This file is copied verbatim from the canonical
> `plugins/PROTOCOL.md` in the main
> [VRTelemetry](https://github.com/Deatron01/VRTelemetry) repo, so this
> plugin's repo is buildable on its own without cloning the Core Hub. The
> main repo's copy is the source of truth if the two ever drift; check there
> for the current protocol version before relying on this one for anything
> beyond getting this plugin running.

What a plugin must implement to connect to this workstation's Event Router
and receive live telemetry. If you are writing a new plugin, this file is
the whole contract — you should not need to read any Core Hub source to
build one.

**Naming:** "the Hub" here means the workstation's own API process (this
repository, `src/interfaces/api/`), extended with the Event Router. It is
*not* `src/central_server`, the separate multi-workstation sync/licensing
service documented in `claude/hub-connection-and-networking.md` — that is a
different machine, a different process, and this protocol has nothing to do
with it.

**Status as of this writing:** the Event Router
(`src/interfaces/api/event_router.py`) is wired into the running
application (`src/core/engine.py`, `src/config/settings.py`,
`src/interfaces/api/container.py`/`app.py`/`dependencies.py`/`routers/recording.py`
-- VRT-28) and verified: `ruff`, `ruff format`, `mypy` and the full
`pytest -m "not hardware"` suite are all green against this wiring, with a
gate added at `tests/characterisation/test_route_contract.py` for the
catalog/install/uninstall/status routes in §7. `/ws/hub/telemetry` is live
on this checkout. **New as of the same session:** every plugin, git- or
local-sourced, must now carry a valid `plugin.json` manifest (the "Flawless
Setup" standard) -- see §5 and
`plugins/PLUGIN_DEVELOPER_GUIDE.md` before writing one.

---

## 1. Connecting

```
ws://<hub-host>:<hub-port>/ws/hub/telemetry?plugin_id=<your-id>&token=<shared-token>
```

- **`plugin_id`** (query param, optional but strongly recommended): a short,
  stable identifier for your plugin (e.g. `medical-analytics-01`). Used in
  the Hub's logs and in a future status endpoint. Omit it and the Hub
  assigns `anon-1`, `anon-2`, … — fine for a quick test, not for anything
  you'll want to find in a log later.
- **`token`**: required only if the Hub's operator has set
  `PluginBusSettings.shared_token`. When set, it must match exactly, passed
  either as `?token=...` or as the `X-Plugin-Token` header. No token
  configured (the default) means the endpoint accepts any connection that
  can reach it — this is only acceptable while the Hub binds to loopback
  only, exactly the same posture `hub-connection-and-networking.md`
  documents for the workstation API in general.
- If launched by `PluginManager` (the normal case — see §5), your process
  receives `HUB_WS_URL` and `HUB_PLUGIN_TOKEN` as environment variables
  already pointed at the right place. Build the query string from those;
  do not hardcode a host or port.

The connection is plain WebSocket text frames, each one a JSON object (UTF-8,
one message per `.send`/`.recv` — never multiple JSON objects concatenated
in one frame, never a partial object split across frames).

## 2. Message envelope

Every message the Hub sends you has this shape:

```json
{ "protocol_version": 1, "type": "<message-type>", "...": "..." }
```

**`protocol_version`** (int, always present): bumped only when the *shape*
of a message changes in a way that could make you misinterpret it — a field
renamed or removed, a new required field, or (critically) the frame column
order changing. **Check it.** A plugin that silently proceeds against a
`protocol_version` it wasn't written for is exactly the "same length,
different order" bug that was caught and fixed in this codebase's own
`FIELD_NAMES` constant before it ever shipped (see
`src/core/datatypes.py`) — don't reintroduce the same failure one process
over. Refuse to process (log loudly, disconnect, or degrade to
"logging-only mode") a `protocol_version` higher than the one you were
written against; a *lower* one you may still be able to handle if you know
what changed between versions.

**`type`** (string, always present): one of the message types in §3.
**Ignore any `type` you don't recognise rather than erroring** — see the
compatibility rules in §6; this is how the Hub adds new event types without
breaking every existing plugin.

## 3. Message types (v1)

### `session_start` — implemented

```json
{
  "protocol_version": 1,
  "type": "session_start",
  "session_id": "20260913_142233"
}
```

Sent once when a recording begins. `session_id` matches the Hub's own
session id (same value written into `vr_telemetry_<session_id>.parquet`).

> **Known gap in the current wiring**: the reference implementation of
> `WebSocketBroadcastSink.start()` sends only `type` and `session_id`.
> `consent_id` and `patient_id` are *not yet included*, though the plan doc
> (`claude/vr-telemetry-hub-plugin-architecture-plan.md` §2) describes
> plugins reading a `consent_id` off this event to make their own output
> traceable. If your plugin needs it before that's added upstream: patch
> `WebSocketBroadcastSink.__init__`/`.start()` to accept and include it
> (`TelemetryEngine` has `self.subject_metadata["M-IV_Static_Metadata"]`
> available at the point it constructs the sink), or treat its absence as
> "not yet available" rather than assuming a `None` means "no consent" —
> **the Hub has already gated recording on consent by the time you see any
> event at all; the absence of the field here says nothing about whether
> consent exists.**

### `telemetry_frame` — implemented

```json
{
  "protocol_version": 1,
  "type": "telemetry_frame",
  "session_id": "20260913_142233",
  "frame": { "frame_index": 1042, "timestamp_ns": 173958..., "hmd_pos_x": 0.12, "...": "..." }
}
```

Sent once per accepted telemetry sample — up to 120 Hz, commonly ~90 Hz.
`frame`'s keys are exactly `TelemetryFrame`'s field names
(`src/core/datatypes.py`'s `FIELD_NAMES`); see §4 for the full field
reference. This is the *same data* that reaches the Parquet file, at the
same rate, for the same accepted samples — nothing is decimated,
re-sampled, or filtered for the plugin path.

### `session_stop` — implemented

```json
{ "protocol_version": 1, "type": "session_stop", "session_id": "20260913_142233" }
```

Sent once when the recording ends (normally or on failure). No
`total_frames`/`failure_reason` in v1 — if you need those, they're on the
engine at teardown (`self.frames_recorded`, `self.failure_reason`) and would
need to be added to `WebSocketBroadcastSink.stop()`'s payload upstream; flag
it as a wanted addition rather than reading it as available today.

### `questionnaire_submitted` — **not implemented, contract proposed only**

```json
{
  "protocol_version": 1,
  "type": "questionnaire_submitted",
  "session_id": "20260913_142233",
  "instrument": "ssq",
  "items": { "general_discomfort": 2, "fatigue": 1, "...": "..." }
}
```

`instrument` is `"ssq"` or `"nasa_tlx"`; `items` maps each instrument's item
name (see `SSQ_ITEMS`/`NASA_TLX_ITEMS` in
`plugins/medical-plugin-01/ssq_nasa_tlx.py`, relocated unmodified from
`src/analytics/questionnaires.py`) to the participant's raw rating. **The
Hub does not publish this event yet.** `plugins/medical-plugin-01/app.py`
already has a handler for it (`_score_questionnaire`), written against this
proposed shape, so that wiring it up on the Hub side is the only remaining
step — see `claude/vr-telemetry-hub-plugin-architecture-plan.md` VRT-29 for
the three options on how (and whether) to wire it.

### `consent_withdrawn` — **not implemented, not yet designed**

Proposed, not specified: notify connected plugins when a participant's
consent scope narrows mid-session (`WithdrawalScope`, e.g.
`SPEECH_RECORDING_ONLY`), so a plugin can stop processing what it's no
longer permitted to. This is additive to the Hub's own enforcement, never a
replacement for it — see the plan doc §2 for why consent *decisions* can
never live in a plugin. Track VRT-30 before depending on this.

## 4. `telemetry_frame`'s `frame` object — field reference

Every key below is present on every frame (defaults, not omitted, when a
source has nothing to report — e.g. `battery_hmd = -1.0` means "unknown,"
not "absent"). Types: `frame_index` is an int; `timestamp_ns` is an int
(nanoseconds); every other field is a float, including the four
`*_tracking_valid` flags (`0.0`/`1.0`, not booleans — matches the Parquet
column types exactly, since this is the same data).

| Field(s) | Meaning |
|---|---|
| `frame_index` | Sequential index from the acquisition loop (not the same as row count in Parquet — see `TelemetryEngine.frames_polled` vs `frames_recorded` if you need that distinction). |
| `timestamp_ns` | Nanosecond timestamp. The runtime's display time on OpenXR backends (`app_fps` is only meaningful then — see `IVRBackend.timestamp_is_display_time`); a local monotonic clock read on others. Don't assume cross-backend comparability. |
| `hmd_pos_x/y/z`, `hmd_rot_x/y/z/w` | Headset pose. Position in metres, quaternion `x,y,z,w`. **OpenXR runtime convention** — right-handed, +Y up, −Z forward (Khronos OpenXR 1.0 spec) — applied with no conversion; see `plugins/ros-unity-bridge/coordinate_convert.py` if you need ROS's REP-103 convention instead. |
| `left_pos_x/y/z`, `left_rot_x/y/z/w`, `left_trigger`, `left_grip`, `left_joy_x/y` | Left controller pose and analog inputs (trigger/grip 0–1, joystick −1–1). |
| `right_pos_x/y/z`, `right_rot_x/y/z/w`, `right_trigger`, `right_grip`, `right_joy_x/y` | Right controller, same layout. |
| `left_eye_pos_x/y/z`, `left_eye_rot_x/y/z/w`, `right_eye_pos_x/y/z`, `right_eye_rot_x/y/z/w` | Per-eye gaze pose, when the backend supports eye tracking. |
| `hmd_tracking_valid`, `left_tracking_valid`, `right_tracking_valid`, `eye_tracking_valid` | Whether the corresponding pose above is real tracking data this sample (`1.0`) or a stub (`0.0`) — **check before using any pose field**; the Hub itself refuses to record a frame with zero valid sources at all (`TelemetryEngine._run_pcvr_mode`'s `has_valid_source` check), but an individual source (e.g. eyes) can still be invalid on an otherwise-valid frame. |
| `left_pupil_size`, `right_pupil_size` | Pupil diameter, when available. |
| `heart_rate_bpm` | From a connected biometric sensor, when available. |
| `distance_to_boundary` | Distance to the guardian/chaperone boundary; `-1.0` = unknown. |
| `app_fps` | Only meaningful when the backend's `timestamp_is_display_time` is true (currently OpenXR only) — `0.0` otherwise, not a real measurement. |
| `event_marker` | Researcher-set discrete marker (`POST /api/session/mark`). `0.0` = none set. |
| `battery_hmd`, `battery_left`, `battery_right` | Battery level 0–100; `-1.0` = unknown. |
| `haptic_left_intensity`, `haptic_right_intensity` | Current haptic pulse intensity this instant (auto-expires; see `LiveExperimentState`), not a command. |
| `gaze_focal_distance` | Computed binocular convergence distance; `-1.0` = not computable this sample. |
| `voice_amplitude_db` | Microphone level, when a hardware monitor is attached. |
| `cpu_utilization`, `gpu_utilization` | Host machine load, sampled at low frequency and folded into every frame. |
| `scene_id` | Researcher/app-set current scene (`POST /api/session/scene`); `1.0` = the documented "Menu" default. |
| `target_obj_pos_x/y/z` | Researcher-set target object position (`POST /api/session/target`). |
| `dist_to_target_left`, `dist_to_target_right` | Distance from each controller to `target_obj_pos`, when that controller is tracking. |

This table is generated by reading `src/core/datatypes.py` and
`src/core/synchronizer.py` directly; if a field's behaviour here ever seems
wrong, those two files (plus `src/core/derived_metrics.py` for
`gaze_focal_distance`/distance calculations) are the source of truth, not
this document.

## 5. `plugin.json` and registering your plugin

**Every plugin must carry a `plugin.json` manifest at its repository root**
-- the "Flawless Setup" standard. `PluginManager` refuses to provision a
plugin with no manifest, or one that fails validation (missing field, or a
`protocol_version` this Hub doesn't speak), before it is ever cloned into a
venv or spawned. The full manifest shape, a filled-in example, and the
matching `README.md` template are in
**`plugins/PLUGIN_DEVELOPER_GUIDE.md`** -- read that before writing a new
plugin; this section only covers how the manifest and `registry.json`
relate.

`PluginManager` (`src/plugin_manager/manager.py`) reads
`plugins/registry.json` on Hub startup. One entry per plugin:

```json
{
  "plugin_id": "your-plugin-id",
  "source": "local",
  "local_path": "plugins/your-plugin-directory",
  "enabled": true,
  "restart_on_crash": true,
  "max_restarts_per_hour": 6,
  "env": { "YOUR_OWN_VAR": "value" }
}
```

`registry.json`'s job is now just *where to find your plugin and whether to
run it* -- `entrypoint` and `requirements_file` are read from your
`plugin.json` instead (the manifest is the authority on how to run your
plugin; see `PluginManager._start_one`'s docstring for why). `plugin_id`
here must match `plugin.json`'s own `plugin_id` exactly, or the plugin is
refused with a clear error rather than started under the wrong identity.

Use `"source": "git"` with `"repo_url"`/`"ref"` instead of `"local_path"`
once your plugin has its own repository — `PluginManager` clones it under
its own checkout directory and keeps it updated to `ref` on every boot (hard
reset — see `src/plugin_manager/git_ops.py`'s docstring on why local edits
in a git-sourced checkout don't survive an update).

`PluginManager` provisions your plugin *for* you: creates an isolated
virtual environment under its own `venvs_dir` (your `requirements.txt`
installs there, never into the Hub's own interpreter — see
`src/plugin_manager/env_installer.py`), resolves the literal token
`"python"` in your manifest's `entrypoint` to that venv's interpreter, and
launches your process with `cwd` set to your plugin's directory. A crashed
plugin is restarted with exponential backoff up to `max_restarts_per_hour`,
then left stopped (check `plugin_<your-id>.log` under the Hub's
`Logs/plugins/` directory).

**You don't have to edit `registry.json` by hand for a catalog plugin.** A
git-sourced plugin listed in the Central Server's approved catalog
(`GET /api/plugins/catalog` on the hub, proxied by the workstation's own
`GET /api/plugins/catalog`) can be installed with
`POST /api/plugins/install {"plugin_id": "..."}` from the workstation API --
this writes the `registry.json` entry for you, clones, validates the
manifest, provisions the venv and starts it, all in one call. See
`src/interfaces/api/routers/plugins.py` and §7 below.

## 6. Compatibility rules — what makes a plugin "Hub-compatible"

A plugin is compatible with this Hub if, and only if, it:

1. **Ignores any `type` it doesn't recognise.** New event types get added
   (see §3's "not implemented" entries) without a `protocol_version` bump,
   specifically so existing plugins keep working unmodified. An `if/elif`
   chain that logs-and-continues on an unknown type (both example plugins
   do this) is correct; a chain that raises on an unknown type is not.
2. **Checks `protocol_version` and refuses to guess past one it wasn't
   written for**, rather than indexing into `frame` positionally or
   assuming a field exists. Always access `frame` fields by name, never by
   position — the whole reason `FIELD_NAMES` exists on the Hub side is that
   position is exactly what silently drifts (§2).
3. **Never blocks.** The Hub's per-connection queue is small on purpose
   (`max_queue_per_client`, default 240 ≈ 2s at 120Hz) and drops your
   *oldest* undelivered frame once full rather than blocking the Hub — but
   a plugin whose own processing of a received frame blocks for a long time
   stalls its own consumption of the WebSocket, which is what causes those
   drops in the first place. Keep per-frame handling fast (buffer/aggregate,
   don't do heavy synchronous work inline — see
   `plugins/medical-plugin-01/app.py`'s `SessionAggregate` for the pattern).
4. **Reconnects with backoff**, doesn't assume message ordering survives a
   reconnect, and doesn't assume exactly one `session_start`/`session_stop`
   pair per process lifetime (a plugin that's down when a session starts and
   comes back up mid-session will see `telemetry_frame`s for a
   `session_id` it never saw a `session_start` for — both example plugins
   handle this by no-op'ing on an unknown `session_id` rather than crashing).
5. **Never assumes it gates anything.** If your plugin is down, crashed,
   slow, or was never started, recording continues identically — see
   `src/storage/tee_sink.py`'s docstring for the mechanism that guarantees
   this. Do not build a plugin whose absence is meant to be noticed by the
   recording path; that is not a supported integration point, and the
   consent gate specifically is designed to be impossible to move here (plan
   doc §2).
6. **Publishes nothing back the Hub currently reads.** v1 is
   Hub → plugin only; the Event Router's WebSocket endpoint reads and
   discards anything a plugin sends (logged at debug level). Don't build a
   plugin whose correctness depends on a response.

Two working reference implementations of all six rules exist in this
directory: `plugins/medical-plugin-01/` and `plugins/ros-unity-bridge/`.

## 7. The catalog & install API

A researcher does not need to touch `registry.json` or a terminal to add a
plugin the operator has approved. Three workstation routes
(`src/interfaces/api/routers/plugins.py`) and one Central Server route
(`src/central_server/plugin_catalog.py`) do it end to end:

- **`GET /api/plugins/catalog`** (Central Server) -- the operator-curated
  allowlist: `plugin_id`, `name`, `description`, `repo_url`, `ref`,
  `homepage`, `maintainer` for every approved plugin. Unauthenticated, like
  `/health` -- it carries no participant data. Edit
  `src/central_server/plugin_catalog.json` to add or remove an entry (see
  that module's docstring for why it's a file, not a database table, today).
- **`GET /api/plugins/catalog`** (workstation) -- a thin proxy of the above,
  so the researcher-facing UI only ever talks to this workstation's own
  loopback API.
- **`POST /api/plugins/install {"plugin_id": "..."}`** (workstation) --
  looks the id up in the catalog (never trusts a client-supplied
  `repo_url`), then calls `PluginManager.install_plugin`: clone, validate
  `plugin.json`, provision the isolated venv, start the process, and persist
  the `registry.json` entry, all before the request returns. A 422 with the
  underlying reason (a `PluginGitError`/`PluginEnvironmentError`/
  `PluginManifestError`) means provisioning failed -- nothing is left
  half-installed and silently reported as success.
- **`POST /api/plugins/uninstall {"plugin_id": "..."}`** (workstation) --
  stops the process if running and removes it from `registry.json`.
- **`GET /api/plugins/status`** (workstation) -- every plugin the workstation
  knows about, installed or not, running or not (`PluginStatus`: `installed`,
  `enabled`, `running`, `pid`, `restarts`, `last_exit_code`, `last_error`,
  plus `name`/`description`/`version` from its manifest).

These routes are what the Electron app's Plugins panel drives (React,
`src/frontend/VRTelemetry/src/pages/Plugins.tsx`) -- "browse catalog,
Install, see status, Uninstall" with no terminal involved.
