# VPS deployment: MEP Component Extractor

Use Ubuntu 24.04 LTS (Ubuntu 22.04 or Debian 12 also work). A practical starting
size is 2 vCPU, 4 GB RAM, and 40 GB SSD because PDF/DXF analysis is CPU- and
memory-intensive. Run the commands below as the normal sudo-enabled account
provided by the VPS company.

## What goes where

| Item | VPS location | Owner | Purpose |
|---|---|---|---|
| Application repository | `/srv/mep/app` | `mep:mep` | Code, templates, static files, and `sets.dxf` |
| Python virtual environment | `/srv/mep/venv` | `mep:mep` | Installed Python packages |
| Uploads and generated reports | `/srv/mep/uploads` | `mep:mep` | Persistent writable job data |
| Secrets and runtime settings | `/etc/mep/mep.env` | `root:mep`, mode `640` | Login and session secrets |
| systemd unit | `/etc/systemd/system/mep.service` | `root:root` | Starts and monitors Gunicorn |
| Nginx site | `/etc/nginx/sites-available/mep` | `root:root` | Public HTTP/HTTPS reverse proxy |

Do not put passwords in GitHub, `web_app.py`, the systemd unit, or Nginx.

## 1. Point the domain at the VPS (optional initially)

At the DNS provider, create an `A` record for the chosen domain or subdomain
pointing to the VPS public IPv4 address. You can test by IP first, but a domain
is needed for the Let's Encrypt HTTPS step.

## 2. Connect and install system packages

From PowerShell on your computer:

```powershell
ssh YOUR_SSH_USER@YOUR_VPS_IP
```

On the VPS:

```bash
sudo apt update
sudo apt upgrade -y
sudo apt install -y git python3 python3-pip python3-venv nginx ufw certbot python3-certbot-nginx
```

## 3. Create the service account and directories

```bash
sudo useradd --system --home-dir /srv/mep --create-home --shell /usr/sbin/nologin mep
sudo install -d -o mep -g mep -m 0755 /srv/mep/app /srv/mep/uploads
sudo install -d -o root -g mep -m 0750 /etc/mep
sudo chmod 0751 /srv/mep
sudo chmod 0750 /srv/mep/uploads
```

The execute-only permission for other users on `/srv/mep` lets the Nginx worker
reach public files under `/srv/mep/app/static` without allowing it to list the
application directory. Uploads remain private to the `mep` service account.

If `useradd` says `mep` already exists, continue and run:

```bash
sudo chown -R mep:mep /srv/mep
```

## 4. Put the application in `/srv/mep/app`

After the deployment commit is on GitHub:

```bash
sudo -u mep git clone https://github.com/Hassan-Amanat-Ali/PDFexrtractor.git /srv/mep/app
```

The clone must contain `web_app.py`, `requirements_web.txt`, `templates/`,
`static/`, `taxonomy.json`, and `sets.dxf` directly inside `/srv/mep/app`.

## 5. Create the Python environment

```bash
sudo -u mep python3 -m venv /srv/mep/venv
sudo -u mep /srv/mep/venv/bin/python -m pip install --upgrade pip
sudo -u mep /srv/mep/venv/bin/pip install -r /srv/mep/app/requirements_web.txt
```

## 6. Put secrets in `/etc/mep/mep.env`

```bash
sudo cp /srv/mep/app/deploy/mep.env.example /etc/mep/mep.env
sudo chown root:mep /etc/mep/mep.env
sudo chmod 640 /etc/mep/mep.env
sudo nano /etc/mep/mep.env
```

Keep `MEP_USER` as `admin` or choose another login name. Replace
`MEP_PASSWORD` with a long unique password. Generate the session key on the VPS:

```bash
openssl rand -hex 32
```

Paste that output after `MEP_SECRET_KEY=`. Do not include spaces around `=`.
Leave `MEP_UPLOAD_DIR=/srv/mep/uploads` unchanged.

## 7. Install and start the systemd service

```bash
sudo cp /srv/mep/app/deploy/mep.service /etc/systemd/system/mep.service
sudo systemctl daemon-reload
sudo systemctl enable --now mep
sudo systemctl status mep --no-pager
curl -fsS http://127.0.0.1:5000/healthz
```

The final command should print `{"status":"ok"}`. The service deliberately
uses one process because active job status is stored in process memory; four
threads keep polling and downloads responsive during analysis.

If it does not start:

```bash
sudo journalctl -u mep -n 100 --no-pager
```

## 8. Install the Nginx site

```bash
sudo cp /srv/mep/app/deploy/nginx.conf /etc/nginx/sites-available/mep
sudo nano /etc/nginx/sites-available/mep
```

Change `YOUR_DOMAIN_OR_IP` to the real domain or VPS IP, then enable it:

```bash
sudo ln -s /etc/nginx/sites-available/mep /etc/nginx/sites-enabled/mep
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl reload nginx
```

Open `http://YOUR_DOMAIN_OR_IP` and sign in with the values from
`/etc/mep/mep.env`.

## 9. Enable the firewall safely

Allow SSH before enabling the firewall so the current SSH route remains open:

```bash
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'
sudo ufw enable
sudo ufw status
```

If the VPS uses a nonstandard SSH port, allow that port before `ufw enable`.

## 10. Add HTTPS when DNS is working

```bash
sudo certbot --nginx -d YOUR_DOMAIN
sudo certbot renew --dry-run
```

Use the HTTPS URL after this succeeds.

## Updating the deployed application

After new code has been pushed to GitHub:

```bash
sudo -u mep git -C /srv/mep/app pull --ff-only
sudo -u mep /srv/mep/venv/bin/pip install -r /srv/mep/app/requirements_web.txt
sudo systemctl restart mep
curl -fsS http://127.0.0.1:5000/healthz
```

## Useful checks

| Command | Purpose |
|---|---|
| `sudo systemctl status mep --no-pager` | Service state |
| `sudo journalctl -u mep -f` | Live application logs |
| `curl -fsS http://127.0.0.1:5000/healthz` | Direct app health |
| `sudo nginx -t` | Validate Nginx configuration |
| `sudo tail -f /var/log/nginx/error.log` | Nginx errors |
| `df -h /srv/mep` | Available upload/report disk space |
| `du -sh /srv/mep/uploads` | Space used by job files |

Completed job files are not automatically deleted. Monitor
`/srv/mep/uploads` and add a retention policy once the desired retention period
is known.
