# Backing off polling of unresponsive devices

Status: proposal, not implemented. Written 2026-09-24 after end-to-end testing of the Modbus and BACnet drivers
against their protocol proxies.

## Problem

When a device stops answering, the driver keeps polling it at the configured interval, and every poll runs the
protocol's full timeout-and-retry cycle for every request in the poll. Nothing about the current design shortens
the next attempt after a failure. The cost is paid on every interval for as long as the device is down.

The cost is not confined to the dead device:

- **Modbus.** Units behind one TCP gateway share one connection and one request queue in the proxy (this is
  required: the serial bus behind the gateway cannot carry two requests at once). A silent unit holds that queue
  for `timeout * (retries + 1)` seconds per request, roughly 12 s at defaults, and every other unit on the gateway
  waits behind it. Healthy units are delayed or time out on the driver side.
- **BACnet.** bacpypes3's `BatchRead` works through a device's references sequentially in ReadPropertyMultiple
  chunks of ten. A silent device costs one APDU timeout-and-retry cycle (12 s at defaults) per chunk. A device with
  100 points and the default `max_per_request` of 24 takes about a minute per poll to fail. Other devices are not
  blocked (each has its own DriverAgent and BACnet/IP has no shared bus), but that DriverAgent's poll cycle is
  saturated with failures.
- **Both.** Each failed point is logged at warning level on every poll, so a single dead device produces a steady
  stream of identical warnings for the length of the outage.

## Analysis

The timeout layering has been made explicit in both drivers (device timeout < proxy IPC callback limit < driver
reply wait), so each failure is now bounded and reported correctly. What remains is that the *rate* of attempts does
not respond to failure. The fix belongs in the base driver rather than in either interface because:

- The pattern is protocol-independent: repeated total failure of a remote, then eventual recovery.
- `DriverAgent.poll_data` already sees every poll's results and errors for a remote, which is exactly the signal
  needed.
- Interfaces should stay simple protocol translators; scheduling policy is the platform driver's concern.

Two subtleties shape the design:

- **Partial failure is not unresponsiveness.** A device answering some points and rejecting others (illegal
  address, unsupported property) is healthy. Only a poll with no successful points at all should count.
- **Shared media.** In Modbus, suspending a dead unit helps its neighbours precisely because it stops consuming the
  gateway's queue. The design must skip the poll entirely (no request issued), not merely ignore the result.

## Design

### State (per remote, in `DriverAgent`)

- `consecutive_failures: int`
- `suspended_until: datetime | None`
- `backoff_interval: float` (current retry spacing)

### Detection

After each poll, if the interface returned no successful values for the requested points, increment
`consecutive_failures`; otherwise reset it to zero and clear any suspension. When the count reaches
`unresponsive_threshold` (default 3), suspend the remote: set `backoff_interval` to the remote's polling interval and
`suspended_until` to now plus that interval.

### Backoff

While `suspended_until` is in the future, `poll_data` returns immediately without calling the interface. The poll
scheduler is untouched, so other remotes' timing is unaffected and the suspended remote costs nothing on the wire.
When the deadline passes, the next scheduled poll runs as a probe. On failure, double `backoff_interval` up to
`backoff_max_interval` (default 600 s) and set a new deadline. On success, clear the suspension and resume normal
polling.

### Probing

To make probes cheap, `BaseInterface` gains an optional `probe() -> bool` with a default implementation that runs the
normal poll. Interfaces may override it:

- Modbus: read one configured register of the unit through the proxy.
- BACnet: unicast Who-Is (or read `object-identifier`) via the proxy's `QUERY_DEVICE`.

### Explicit requests

`get_point`, `set_point`, and their multiple-point forms bypass the suspension: an operator or agent asking for a
point has a reason, and a success clears the suspension.

### Reporting

- On suspension: one warning naming the remote, the failure count, and the retry interval. Per-point warnings are
  suppressed while suspended.
- On each failed probe: one debug line with the next retry time.
- On recovery: one info line.
- Health: publish the remote as unreachable through the existing heartbeat/health mechanism while suspended.
- Publishes: none during suspension. Consumers see stale timestamps rather than repeated errors.

### Configuration (on `RemoteConfig`)

| Field | Default | Meaning |
|---|---|---|
| `backoff_enabled` | `true` | Turn the mechanism off for a remote. |
| `unresponsive_threshold` | `3` | Consecutive fully-failed polls before suspending. |
| `backoff_max_interval` | `600` | Longest spacing between probes, in seconds. |

Per remote rather than per point, because the condition being tracked is the device.

## Open questions

- Should a suspended remote's points be published with `None` values and a health flag, so downstream agents see an
  explicit state rather than silence? This interacts with the `stale_timeout` handling already in `EquipmentConfig`.
- Poll groups spanning several tables or object types: the "no successes at all" rule handles this, but the interface
  must return a clear signal (empty results) rather than raise.
- Whether the probe should reuse the poll scheduler slot or run out of band.

## Related

- Modbus timeout layering: `volttron.driver.interfaces.modbus.config.ModbusRemoteConfig` (`timeout`, `reply_timeout`,
  `registration_timeout`) and `protocol_proxy.protocol.modbus.modbus_proxy.ModbusProxy.DEFAULT_CALLBACK_TIMEOUT`.
- BACnet timeout layering: `BacnetRemoteConfig` (`apdu_timeout`, `apdu_retries`, `timeout`, `registration_timeout`)
  and `BACnetProxy.callback_timeouts`.
- Per-query fallback in the Modbus proxy is already restricted to device exception responses, so it no longer
  amplifies the cost of a silent device.
