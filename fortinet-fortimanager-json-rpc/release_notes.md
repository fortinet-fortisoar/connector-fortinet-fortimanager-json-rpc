#### What's Improved

Following enhancements have been made to the Fortinet FortiManager JSON RPC Connector in version 1.2.7:

- Workspace locking now reflects behaviour measured against a live appliance rather than assumption:
  - `/securityconsole/install/device` takes a lock again. Without one, an install with pending device-database changes fails inside the queued task while the RPC still reports success.
  - `/securityconsole/install/package`, `/securityconsole/install/device` and `/securityconsole/reinstall/package` now hold their lock until the queued task finishes, and return the task outcome, so an install can no longer fail silently when the caller does not request task tracking.
  - Firmware upgrade (`/um/image/upgrade/ext`) takes no lock, so an upgrade no longer serialises other workers in the ADOM for the duration of the task.
  - A request whose payload carries the `auto_lock_ws` flag is left to FortiManager's own locking instead of being locked twice.
- Workers that share one API key no longer break each other's workspace locks. FortiManager treats every request made with one API key as a single session, so two playbooks on the same key both "owned" an ADOM lock and either one's unlock released the other's, failing its write with `-10147 no write permission`. The connector now serialises API-key workspace operations per FortiManager, key and ADOM with a PostgreSQL advisory lock in FortiSOAR's own database, which every node of an active-active cluster shares, so it holds across HA nodes. The lock ends with its database connection, so a crashed worker cannot leave it held. Outside FortiSOAR's database (for example on a remote agent) a local file lock is used, which only covers workers on that host; there, give each agent its own API key or use username/password authentication.
- Read-only `execute` URLs no longer take a workspace lock. The lock was only ever requested because these carry an `adom` in the payload, and it could not help: each of them returns its full result while another session holds the ADOM lock, so the lock was the one thing that could make the read fail. Affects `/um/image/list`, `/um/image/list/ext`, `/um/image/version/list`, `/um/image/version/list/ext`, `/um/device/list` and `/um/image/upgrade/status`. Previously, listing firmware images during a change window could block behind an unrelated writer for the full retry budget.
- Minimal locking resolves finer scopes in more cases: a single-package `reinstall/package` takes a package lock via its `target[]` shape, and packages nested inside package folders now resolve to the path FortiManager accepts.
- A request with no resolvable ADOM no longer reports itself as the `global` ADOM, which had the side effect of silently skipping locking for any such payload on any URL.
- Device onboarding URLs (`/dvm/cmd/*`) always take the ADOM lock; no finer scope exists for a device that is not registered yet.
- A lock URL that names something that does not exist now fails immediately instead of being retried to the full retry budget. This includes an ADOM that does not exist, which FortiManager rejects with `-11 No permission for the resource` in workspace mode; that was previously retried for about 2.3 hours.
- The **Data** parameter of the **JSON RPC Delete** action is now optional. FortiManager deletes the object addressed by the URL and needs no payload, but the parameter was mandatory, so the ordinary delete-by-URL form could not be expressed from a playbook.
- Workspace locking is now traceable from the connector log:
  - Every call records whether it locked, and when it did not, why (a read-only `get`, an exempt URL, an appliance with workspace mode disabled, or a payload that asked FortiManager to lock server-side).
  - A call that asked for minimal locking but could not resolve a package or device scope reports that it fell back to locking the whole ADOM, which is the difference between running alongside other workers and serialising them.
  - Each lock reports how long it was held, which is the figure other workers wait on.
  - A failed release or commit is reported instead of being discarded. An unlock that fails leaves the package or device locked for every other worker until the session ends, and previously left nothing in the log to explain it.

  The first three are logged at `DEBUG` and `INFO`. FortiSOAR records connector logs at `WARNING` and above by default, so raise `connector_logger_level` in the integrations configuration to see them; failures are reported at `WARNING` and `ERROR` and are recorded either way.
