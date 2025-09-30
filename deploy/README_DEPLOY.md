# Deploy (Ubuntu + systemd)

- Create venv, install requirements.
- Copy \deploy/pricebot.service.example\ to /etc/systemd/system/pricebot.service
- Enable & start, view logs with \journalctl -u pricebot -f\.