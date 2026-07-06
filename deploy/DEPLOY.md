# VPS Deployment Guide — MEP Component Extractor (Web)

Tested on Ubuntu 22.04 LTS / Debian 12. Run every command as your non-root sudo user.

---

## 1. Server preparation

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-pip python3-venv nginx certbot python3-certbot-nginx
```

---

## 2. Upload the project

From your Windows machine (Git Bash or PowerShell):

```bash
# Adjust path and user@your.vps.ip as needed
scp -r "F:/auto extract" user@your.vps.ip:/srv/mep
```

Or with rsync (faster for re-uploads):

```bash
rsync -avz --exclude __pycache__ --exclude dist --exclude build \
      "F:/auto extract/" user@your.vps.ip:/srv/mep/
```

---

## 3. Python virtualenv + dependencies

```bash
cd /srv/mep
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements_web.txt
deactivate
```

---

## 4. Environment variables (credentials)

Create `/srv/mep/.env`:

```bash
cat > /srv/mep/.env << 'EOF'
MEP_USER=admin
MEP_PASSWORD=YourStrongPassword123!
MEP_SECRET_KEY=generate-a-random-64-char-string-here
EOF
chmod 600 /srv/mep/.env
```

Generate a random secret key:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

---

## 5. systemd service

```bash
sudo nano /etc/systemd/system/mep.service
```

Paste:

```ini
[Unit]
Description=MEP Component Extractor (Flask / Gunicorn)
After=network.target

[Service]
User=www-data
Group=www-data
WorkingDirectory=/srv/mep
EnvironmentFile=/srv/mep/.env
ExecStart=/srv/mep/venv/bin/gunicorn \
    --workers 2 \
    --bind 127.0.0.1:5000 \
    --timeout 300 \
    --access-logfile /var/log/mep/access.log \
    --error-logfile /var/log/mep/error.log \
    web_app:app
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo mkdir -p /var/log/mep
sudo chown www-data:www-data /var/log/mep
sudo chown -R www-data:www-data /srv/mep
sudo systemctl daemon-reload
sudo systemctl enable mep
sudo systemctl start mep
```

Check it started:

```bash
sudo systemctl status mep
```

---

## 6. Nginx reverse proxy

```bash
sudo nano /etc/nginx/sites-available/mep
```

Paste (replace `yourdomain.com` with your actual domain or VPS IP):

```nginx
server {
    listen 80;
    server_name yourdomain.com;

    # Increase upload size limit to 100 MB
    client_max_body_size 100M;

    location / {
        proxy_pass         http://127.0.0.1:5000;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
        proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
        proxy_read_timeout 300;
        proxy_send_timeout 300;
    }

    location /static/ {
        alias /srv/mep/static/;
        expires 1d;
    }
}
```

Enable and test:

```bash
sudo ln -s /etc/nginx/sites-available/mep /etc/nginx/sites-enabled/mep
sudo nginx -t
sudo systemctl reload nginx
```

---

## 7. SSL certificate (Let's Encrypt)

You need a domain name pointing to your VPS IP before this step.

```bash
sudo certbot --nginx -d yourdomain.com
```

Certbot will edit your nginx config to add HTTPS and set up auto-renewal. Verify renewal works:

```bash
sudo certbot renew --dry-run
```

---

## 8. Firewall

```bash
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'
sudo ufw enable
```

---

## 9. Updates / redeploy

After uploading new files:

```bash
sudo systemctl restart mep
```

---

## 10. Useful commands

| Command | Purpose |
|---|---|
| `sudo systemctl status mep` | Check service health |
| `sudo journalctl -u mep -f` | Tail live logs |
| `sudo tail -f /var/log/mep/error.log` | Gunicorn errors |
| `sudo systemctl restart mep` | Restart after code changes |
| `sudo nginx -t && sudo systemctl reload nginx` | Reload nginx config |

---

## Directory structure on server

```
/srv/mep/
├── web_app.py          ← Flask app
├── pdf_parser.py
├── vector_analyzer.py
├── report_generator.py
├── ml_detector.py
├── result_combiner.py
├── taxonomy.json
├── sets.dxf            ← keep updated here
├── requirements_web.txt
├── venv/               ← Python virtualenv
├── uploads/            ← auto-created, stores per-job PDFs + reports
├── templates/
│   ├── base.html
│   ├── login.html
│   ├── index.html
│   ├── waiting.html
│   ├── results.html
│   └── error.html
└── static/
    └── css/style.css
```

---

## Changing the password

Edit `/srv/mep/.env` and update `MEP_PASSWORD`, then:

```bash
sudo systemctl restart mep
```

---

## Adding multiple users (optional)

The current setup supports one user. For multiple users, replace the credential check in
`web_app.py` lines with a dict:

```python
USERS = {
    'alice': 'password1',
    'bob':   'password2',
}
# In login route:
if USERS.get(request.form.get('username')) == request.form.get('password'):
```

Store the dict in `.env` as JSON or in a simple file — do not hardcode passwords in source.
