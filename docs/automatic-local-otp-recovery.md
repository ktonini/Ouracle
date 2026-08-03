# Automatic local OTP recovery

Cracked Oura can recover an expired Oura web session without manual copy/paste by reading a newly received verification code from a local Thunderbird or Betterbird cache.

## Privacy and safety

- Deterministic only: no AI model, cloud service, IMAP credentials, or external mailbox API is involved.
- Prefer the local Betterbird extension's live mailbox RPC when it is available. It reads the current Inbox through Thunderbird itself.
- Fall back to read-only local Inbox mbox files when Betterbird is unavailable, so standalone Thunderbird still works.
- The app never uploads, changes, marks read, moves, or deletes email.
- It accepts only a message that is newer than the Oura code request, with the configured sender and subject, and containing a configured code pattern.
- Automatic retrieval is opt-in. Disable it at any time with `auto_otp_enabled: false`.
- Betterbird launching is also opt-in within live-mailbox mode. If Betterbird is not running, the app can discover it through `PATH` or standard OS install locations and start it without a shell command.

## Supported clients

Thunderbird and Betterbird share the Thunderbird profile format. The default path discovery covers their usual Windows, Linux, and macOS profile locations. The current implementation reads the standard Thunderbird mbox cache (`ImapMail/.../INBOX` or `Mail/.../INBOX`).

If a client uses Maildir rather than mbox, manual OTP entry remains available.

## Configuration

The desktop app stores `oura_config.json` under its user-data directory. On Windows that is:

```text
%APPDATA%\CrackedOura\oura_config.json
```

Example for a generic Oura mailbox:

```json
{
  "auto_otp_enabled": true,
  "auto_otp_sender": "support@ouraring.com",
  "auto_otp_subject": "One time password",
  "auto_otp_code_pattern": "(?:one\\s*time\\s*password|verification\\s*code)\\D{0,80}\\b(\\d{6})\\b",
  "auto_otp_profile_root": "",
  "auto_otp_poll_seconds": 3,
  "auto_otp_timeout_seconds": 120,
  "auto_otp_live_mailbox_enabled": true,
  "auto_otp_mailbox_api_url": "http://127.0.0.1:8766",
  "auto_otp_betterbird_launch_enabled": true,
  "auto_otp_betterbird_executable": "",
  "auto_otp_betterbird_startup_wait_seconds": 60
}
```

Set `auto_otp_profile_root` only when profile discovery cannot find the client. It must point to the client `Profiles` directory, for example:

```text
C:\Users\<user>\AppData\Roaming\Thunderbird\Profiles
```

`auto_otp_betterbird_executable` is optional. Leave it empty to use `PATH` and conventional installation locations. Set it only for a portable/custom install, using a path appropriate to the current machine. `auto_otp_betterbird_startup_wait_seconds` is the maximum time to wait for Betterbird and its local mailbox bridge to initialize; the default is one minute.

## Runtime behavior

1. Oura requests a verification email in its Playwright login UI.
2. When live mailbox mode is enabled, Cracked Oura checks for Betterbird, launches it when configured and not already running, and waits up to one minute for the local mailbox bridge to initialize. It then asks the Betterbird extension to wait for a current matching Inbox message. When Betterbird is unavailable, it polls the local Thunderbird cache for up to 120 seconds.
3. When it finds a fresh matching message, it submits the OTP to the active Oura session and resumes the interrupted sync.
4. If no safe match appears, it leaves the ordinary manual OTP prompt in place.

Automatic recovery is used by Settings login, scheduled sync, dashboard Sync now, export-ready checks, and existing-export download paths. If automatic recovery cannot find a message, each path falls back to manual entry.

No OTP value is written to application logs.
