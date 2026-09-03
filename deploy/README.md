# Deploying the Pillar 4 web app

Two long-running processes, both wrapped by systemd templates in this
directory:

- **`bagpipe-api`** — FastAPI (`bag app serve`), accepts uploads, enqueues
  jobs, answers `GET /jobs/{id}` polls. Cheap, stateless, safe to restart
  anytime.
- **`bagpipe-worker`** — Huey consumer (`bag app worker`), runs the actual
  stage graph (CAT12 → predict → report → email) for one job at a time.

They're split so a slow CAT12 run never blocks new uploads or status polls.

## Install

```bash
sudo useradd -r -m -d /opt/bagpipe bagpipe
sudo -u bagpipe git clone <repo-url> /opt/bagpipe
cd /opt/bagpipe
sudo -u bagpipe uv sync
sudo -u bagpipe cp config/local.yaml.example config/local.yaml
# fill in config/local.yaml: real paths, app.smtp_*/from_address, app.turnstile_*
```

Build (or copy) `container/cat12.sif` to the path in `config/local.yaml`'s
`paths.cat12_apptainer_image` before starting the worker — see
`docs/cat12_container_spec.md`.

## systemd

```bash
sudo cp deploy/systemd/bagpipe-api.service deploy/systemd/bagpipe-worker.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now bagpipe-api bagpipe-worker
sudo journalctl -u bagpipe-api -u bagpipe-worker -f   # tail logs
```

Edit the two `.service` files first — `User`, `WorkingDirectory`, and
`ExecStart`'s venv path are placeholders, not real values (this repo is
public; machine-specific paths never get committed as real values, per
CLAUDE.md).

## Reverse proxy (required)

`bag app serve` binds `127.0.0.1` by default and has **no authentication**.
Put a TLS-terminating reverse proxy in front for anything beyond local
testing — the app handles uploaded medical imaging, so it must never be
reachable over plain HTTP or directly on a public interface. Example nginx:

Get a free TLS cert for your domain with
[Certbot](https://certbot.eff.org/) (`sudo certbot --nginx -d
bagpipe.example.org`) before using the config below — it fills in the
`ssl_certificate` paths for you.

```nginx
limit_req_zone $binary_remote_addr zone=bagpipe_predict:10m rate=2r/h;

server {
    listen 443 ssl;
    server_name bagpipe.example.org;
    ssl_certificate     /etc/letsencrypt/live/bagpipe.example.org/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/bagpipe.example.org/privkey.pem;

    client_max_body_size 200M;   # T1w NIfTI/DICOM zips can run large
    proxy_read_timeout 60s;      # /predict returns fast (202); /jobs polls are cheap

    location /predict {
        limit_req zone=bagpipe_predict burst=2 nodelay;  # per-IP: ~2 uploads/hour
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

The `limit_req` above is a coarse per-IP throttle (catches one script hammering
the endpoint from one address); Turnstile below is the real anti-bot gate.
Adjust `rate=2r/h` to whatever throughput your GPU can actually sustain — see
§ Public-abuse protection.

## Public-abuse protection

Each accepted `/predict` costs roughly an hour of the app's single GPU
(`bagpipe.preprocess`/`bagpipe.app.pipeline.segment`'s CAT12 run). Since this
app is meant to be open to the general public with no login, that single GPU
is the thing to protect — three layers, all already wired in code, that you
turn on via config:

1. **Cloudflare Turnstile** (`app.turnstile_site_key`/`turnstile_secret_key`)
   — a free, privacy-respecting CAPTCHA alternative (no user-facing puzzle in
   most cases). Sign up at [dash.cloudflare.com](https://dash.cloudflare.com)
   (no domain/DNS setup required just for Turnstile), add a Turnstile widget,
   and copy its site key + secret key into `config/local.yaml`. Until these
   are set, `/predict` skips verification entirely (logged as a warning) —
   fine for local dev, **not for a public deployment**.
2. **`app.max_queue_depth`** (default 5) — `/predict` returns `503` once
   this many jobs are already queued/running, instead of letting an
   unbounded backlog build up behind the single GPU.
3. **nginx `limit_req`** above — a blunt per-IP rate limit as a first line of
   defense before a request even reaches the app.

None of these require an account system — the upload page at `GET /` stays
open to anyone, which is what "general public, no login" means here; they
just stop it from being a free unlimited-GPU-time faucet.

## SMTP (sending the report email)

`app.smtp_host`/`app.smtp_port`/`app.smtp_user`/`app.smtp_password`/
`app.from_address` in `config/local.yaml` drive email delivery
(`bagpipe.app.email`). Recommended: a transactional email provider rather
than your own mail server — self-hosted SMTP has a real risk of landing in
spam with no existing sender reputation, and provider free tiers are more
than enough for this app's volume.

**[Resend](https://resend.com)** (free tier: 3,000 emails/month, no credit
card):

1. Sign up, verify a sending domain (or use their shared `onboarding@
   resend.dev` address for testing only — production should use your own
   domain for deliverability).
2. Create an API key.
3. Config:
   ```yaml
   app:
     smtp_host: smtp.resend.com
     smtp_port: 587
     smtp_user: resend          # literal string, not your account name
     smtp_password: <your Resend API key>
     from_address: reports@yourdomain.org   # must match the verified domain
   ```

Any other provider with SMTP support (Postmark, SES, Brevo, ...) works the
same way — host/port/user/password from their dashboard.

## Privacy / retention

Uploaded imaging (defaced T1w + raw CAT12 output) is deleted after each job
finishes unless the uploader passes `retain_uploads=true` on `POST
/predict` — this is the uploader's own explicit per-upload consent, not a
server-wide setting (`bagpipe.app.queue._delete_imaging`). There is no
retention *duration* control yet — an opted-in job's data stays until
someone manually cleans `paths.uploads_dir`.

## Before trusting this in production

- `container/cat12.sif` must be the SNBB-reprocessed version (see
  CLAUDE.md Phase 4: the standalone build's CAT version differs from
  training's CAT12.9/2577) and its §6 reproducibility test
  (`docs/cat12_container_spec.md`) re-run against the current image before
  each container rebuild is trusted for inference.
- `GET /jobs/{id}` has no auth beyond the job ID itself — anyone who knows
  (or guesses) a job's UUID can read its prediction. UUIDv4 isn't
  practically guessable, so this is intentionally treated as a "possession
  of the link is the credential" model (same as e.g. a Google Docs share
  link), not a bug — but don't build anything that leaks job IDs (e.g. a
  public list of recent jobs) without revisiting this.
- Turnstile/`max_queue_depth`/nginx `limit_req` (§ Public-abuse protection)
  must actually be configured, not just present in code — a fresh
  `config/local.yaml` from the example ships with Turnstile unset
  (verification skipped) until you fill in real keys.
- Single worker by design (single GPU) — a burst of uploads queues, it
  doesn't fail; if wait times become a problem, benchmark GPU headroom
  before raising `--workers`.
