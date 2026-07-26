# Automatic local OTP recovery

Cracked Oura can recover an expired Oura web session without manual copy/paste by reading a newly received verification code from a local Thunderbird or Betterbird cache.

## Privacy and safety

- Deterministic only: no AI model, cloud service, IMAP credentials, or external mailbox API is involved.
- Prefer the local Betterbird extension's live mailbox RPC when it is available. It reads the current Inbox through Thunderbird itself.
- Fall back to read-only local Inbox mbox files when Betterbird is unavailable, so standalone Thunderbird still works.
- The app never uploads, changes, marks read, moves, or deletes email.
- It accepts only a message that is newer than the Oura code request, with the configured sender and subject, and containing a configured code pattern.
- Automatic retrieval is opt-in. Disable it at any time with `auto_otp_enabled: false`.

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
  "auto_otp_mailbox_api_url": "http://127.0.0.1:8766"
}
```

Set `auto_otp_profile_root` only when profile discovery cannot find the client. It must point to the client `Profiles` directory, for example:

```text
C:\Users\<user>\AppData\Roaming\Thunderbird\Profiles
```

## Runtime behavior

1. Oura requests a verification email in its Playwright login UI.
2. Cracked Oura first asks the local Betterbird extension to wait for a current matching Inbox message. When Betterbird is not running or its bridge is unavailable, it polls the local Thunderbird cache for up to 120 seconds.
3. When it finds a fresh matching message, it submits the OTP to the active Oura session and resumes the interrupted sync.
4. If no safe match appears, it leaves the ordinary manual OTP prompt in place.

No OTP value is written to application logs.
