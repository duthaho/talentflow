# Headless browser recovery on the QA runner

Use this runbook when `agent-browser open` hangs on the local Linux ARM64
runner even though `agent-browser doctor --offline --quick` passes. It covers
agent-browser 0.27.0 with Snap Chromium 158.0.8127.36, observed on 2026-11-26
on `instance-20260427-2220` (QA runtime `9282626d`).

## Confirmed cause

The default browser profile lives under the task's `TMPDIR`, for example
`/tmp/multica-task-<id>/agent-browser-chrome-<uuid>`. Snap Chromium has a
private `/tmp` mount. Chrome starts and writes its `DevToolsActivePort` there,
but the host-side agent-browser daemon cannot see that file to discover the
random CDP port. Navigation waits instead of connecting to the running browser.

During diagnosis, the same `DevToolsActivePort` path was absent from the host
filesystem but readable through `/proc/<chrome-pid>/root/tmp/...`, containing
a port and browser endpoint. A default fresh session timed out after 29 seconds.
Moving only the profile to Snap's shared home directory made the exact
navigation and title assertion pass within 30 seconds. The quick doctor check
does not test this full navigation path. Existing daemons also owned zombie
Chrome children; their presence alone does not identify the launch failure.

This recovery needs no package, sysctl, sandbox or application change. Keep the
Chrome sandbox enabled. Do not add `--no-sandbox` for this failure.

## Start an isolated session

Run as the same Unix user as the QA task. Use an absolute profile path under
`$HOME/snap/chromium/common`, which both Snap Chromium and the daemon can see.
Each concurrent task needs its own session **and** profile; never share a
logged-in profile between tasks.

```bash
agent-browser --version
agent-browser doctor --offline --quick

mkdir -p "$HOME/snap/chromium/common"
export TF_BROWSER_SESSION="duth124-$$"
export TF_BROWSER_PROFILE
TF_BROWSER_PROFILE=$(mktemp -d "$HOME/snap/chromium/common/talentflow-qa.XXXXXX")

# The deadline covers navigation and title retrieval together.
time timeout 30 bash -c '
  agent-browser --session "$TF_BROWSER_SESSION" \
    --profile "$TF_BROWSER_PROFILE" open https://example.com &&
  test "$(agent-browser --session "$TF_BROWSER_SESSION" get title)" = "Example Domain"
'
```

Pass `--profile` on the first command, before the daemon launches. Later commands
need only `--session`. If a daemon is already running, launch options are ignored;
close your own session first and start again. Do not keep retrying a failed
default session: each attempt can leave more Chrome processes behind.

## Verify Keycloak login and a screenshot

Use the checkout under review and its documented Compose port overrides. Keep
the same `.env` and Compose project for startup, seeding and cleanup. The repo
provides `docker compose up` and `make seed`; it has no `make up` target.

```bash
# In the repository root, after selecting unused ports in the ignored .env:
docker compose config --quiet
docker compose up -d --build --wait --wait-timeout 600
make seed

# Set this to the WEB_PORT selected in .env. Use localhost consistently with
# APP_BASE_URL, Keycloak issuer and the seeded redirect URI.
export TF_WEB_PORT=13000
agent-browser --session "$TF_BROWSER_SESSION" open "http://localhost:$TF_WEB_PORT/reports"
agent-browser --session "$TF_BROWSER_SESSION" snapshot -i
```

Follow the sign-in link if the app first shows its signed-out page. Re-snapshot
after navigation. On the Keycloak form, fill the seeded admin username and use
the locally configured demo password (`DEMO_USER_PASSWORD`, as described in the
README). Keep password input in a private tool call; do not include it in a
transcript, screenshot, committed script or result comment. Do not save browser
state or a HAR as review evidence because it can contain tokens.

After submitting the form, open `/reports` again if login lands on `/candidates`:

```bash
agent-browser --session "$TF_BROWSER_SESSION" open "http://localhost:$TF_WEB_PORT/reports"
agent-browser --session "$TF_BROWSER_SESSION" wait --url "**/reports"
test "$(agent-browser --session "$TF_BROWSER_SESSION" get url)" = \
  "http://localhost:$TF_WEB_PORT/reports"
agent-browser --session "$TF_BROWSER_SESSION" snapshot -i
agent-browser --session "$TF_BROWSER_SESSION" screenshot ./reports-browser-check.png
```

Check that the authenticated admin shell and reports content render, without a
login redirect or error. The main-branch placeholder is not proof of DUTH-56's
reporting behavior: that feature needs its own PR checkout and QA assertions.
Attach only the resulting UI screenshot to the issue; keep it out of Git.

## Cleanup and stale sessions

Close the session you created, even when an assertion fails:

```bash
timeout 10 agent-browser --session "$TF_BROWSER_SESSION" close
```

The private profile may retain cookies and tokens. Once the browser has stopped,
remove only that task's recorded `TF_BROWSER_PROFILE` directory. Never reuse it
for a different task or upload it. For a temporary Compose stack, stop only your
own Compose project with `docker compose down`; retain volumes unless their
deletion was explicitly approved. Undoing this workaround means closing its
session and omitting `--profile` on the next launch; the Snap `/tmp` failure may
return. No host setting needs to be reverted.

Before stopping an older daemon, check the active runs:

```bash
"$MULTICA_CLI_PATH" issue runs DUTH-53 --active --output json
"$MULTICA_CLI_PATH" issue runs DUTH-54 --active --output json
"$MULTICA_CLI_PATH" issue runs DUTH-56 --active --output json
"$MULTICA_CLI_PATH" issue runs DUTH-114 --active --output json
```

An empty issue-run list alone is not proof that a generic/default session is
unused. Identify the session's owner and confirm it is idle before closing it.
Do not use `close --all`, `pkill chrome`, or `pkill agent-browser` on the shared
runner. If closing your own wedged daemon times out, read its exact PID from
`$HOME/.agent-browser/<session>.pid`, inspect that PID's executable and children,
and compare it with `multica daemon status --output json` (invoke through
`"$MULTICA_CLI_PATH"`). Never terminate the Multica daemon. If ownership cannot
be established, leave the old daemon alone and use a new session/profile.

If a profile under Snap's shared directory still fails, capture the bounded
navigation result, browser version, launch arguments and relevant stderr with
secrets redacted. Escalate any required host-level change to duthaho with the
exact proposed command; do not install packages, change sysctls or weaken the
sandbox speculatively.
