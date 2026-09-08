# VPS deployment: MEP Component Extractor

Target: Ubuntu/Debian, 1+ CPU, 1.6+ GB RAM. The web and analysis processes are
separated so the interface remains responsive. A persistent SQLite queue permits
only one analysis at a time and survives browser refreshes and service restarts.

## Layout

| Path | Purpose |
|---|---|
| `/srv/mep/app` | Git checkout |
| `/srv/mep/venv` | Python virtual environment |
| `/srv/mep/data/jobs.sqlite3` | Persistent job queue/history |
| `/srv/mep/data/jobs/<id>/` | Inputs, results, maps and reports |
| `/etc/mep/mep.env` | Secrets and runtime configuration |
| `/etc/systemd/system/mep.service` | Two lightweight web workers |
| `/etc/systemd/system/mep-worker.service` | One analysis worker |

## First deployment

```bash
sudo apt update
sudo apt install -y git python3 python3-pip python3-venv nginx ufw
sudo useradd --system --home-dir /srv/mep --create-home --shell /usr/sbin/nologin mep
sudo install -d -o mep -g mep -m 0755 /srv/mep/app
sudo install -d -o mep -g mep -m 0750 /srv/mep/data
sudo install -d -o root -g mep -m 0750 /etc/mep
sudo chmod 0751 /srv/mep

sudo -u mep git clone https://github.com/Hassan-Amanat-Ali/PDFexrtractor.git /srv/mep/app
sudo -u mep python3 -m venv /srv/mep/venv
sudo -u mep /srv/mep/venv/bin/python -m pip install --upgrade pip
sudo -u mep /srv/mep/venv/bin/pip install -r /srv/mep/app/requirements_web.txt

sudo cp /srv/mep/app/deploy/mep.env.example /etc/mep/mep.env
sudo chown root:mep /etc/mep/mep.env
sudo chmod 0640 /etc/mep/mep.env
sudo nano /etc/mep/mep.env
```

Set a strong `MEP_PASSWORD` and generate `MEP_SECRET_KEY` with:

```bash
openssl rand -hex 32
```

Install both services and Nginx:

```bash
sudo cp /srv/mep/app/deploy/mep.service /etc/systemd/system/mep.service
sudo cp /srv/mep/app/deploy/mep-worker.service /etc/systemd/system/mep-worker.service
sudo cp /srv/mep/app/deploy/nginx.conf /etc/nginx/sites-available/mep
sudo sed -i 's/YOUR_DOMAIN_OR_IP/your-domain-or-server-ip/' /etc/nginx/sites-available/mep
sudo ln -s /etc/nginx/sites-available/mep /etc/nginx/sites-enabled/mep
sudo rm -f /etc/nginx/sites-enabled/default
sudo systemctl daemon-reload
sudo systemctl enable --now mep mep-worker nginx
sudo nginx -t
sudo systemctl reload nginx
```

Enable the firewall only after allowing SSH:

```bash
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'
sudo ufw enable
```

Use Certbot with a domain before production use so credentials and drawings are
not sent over plain HTTP.

## Updates

```bash
sudo -u mep git -C /srv/mep/app pull --ff-only
sudo -u mep /srv/mep/venv/bin/pip install -r /srv/mep/app/requirements_web.txt
sudo -u mep /srv/mep/venv/bin/python -m compileall -q /srv/mep/app
sudo cp /srv/mep/app/deploy/mep.service /etc/systemd/system/mep.service
sudo cp /srv/mep/app/deploy/mep-worker.service /etc/systemd/system/mep-worker.service
sudo systemctl daemon-reload
sudo systemctl restart mep mep-worker
curl -fsS http://127.0.0.1:5000/healthz
```

## Behaviour

- Fast mode runs text extraction and reports, normally in seconds.
- Advanced mode additionally runs vector analysis and map rendering.
- Only one job is analysed at once; additional jobs show their queue position.
- Refreshing or logging out does not lose a job.
- Cancel terminates the current analysis worker and systemd starts a clean one.
- Saved results are retained. Unsaved terminal jobs expire after seven days.
- Each completed job causes the analysis process to exit, releasing all PDF/image memory.

## Checks

```bash
systemctl status mep mep-worker --no-pager
journalctl -u mep-worker -n 100 --no-pager
curl -fsS http://127.0.0.1:5000/healthz
sqlite3 /srv/mep/data/jobs.sqlite3 'select id,status,stage from jobs order by created_at desc limit 10;'
```
