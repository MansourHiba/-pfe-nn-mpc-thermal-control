#!/bin/bash
set -e

SERVICE_NAME="thermal-control.service"
SERVICE_PATH="/etc/systemd/system/${SERVICE_NAME}"
PROJECT_DIR="/home/pi/Desktop/test_final"
PYTHON_SCRIPT="${PROJECT_DIR}/mqtt.py"

echo "=== Vérification des chemins ==="
if [ ! -f "$PYTHON_SCRIPT" ]; then
  echo "ERREUR: mqtt.py introuvable: $PYTHON_SCRIPT"
  echo "Corrige PROJECT_DIR dans ce script ou place mqtt.py dans /home/pi/Desktop/test_final"
  exit 1
fi

echo "=== Création du service systemd ==="
sudo tee "$SERVICE_PATH" > /dev/null <<EOF
[Unit]
Description=NN-MPC Thermal Control MQTT Service
After=network-online.target mosquitto.service influxdb.service
Wants=network-online.target

[Service]
Type=simple
User=pi
WorkingDirectory=${PROJECT_DIR}
Environment=PYTHONIOENCODING=utf-8
ExecStart=/usr/bin/python3 ${PYTHON_SCRIPT}
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

echo "=== Rechargement systemd ==="
sudo systemctl daemon-reload

echo "=== Détection utilisateur Node-RED ==="
NR_USER="${SUDO_USER:-pi}"
echo "Utilisateur autorisé pour Node-RED/systemctl: $NR_USER"

echo "=== Autorisation sudo sans mot de passe pour ce service uniquement ==="
SUDOERS_FILE="/etc/sudoers.d/thermal-control"
sudo tee "$SUDOERS_FILE" > /dev/null <<EOF
${NR_USER} ALL=(ALL) NOPASSWD: /usr/bin/systemctl start thermal-control.service, /usr/bin/systemctl stop thermal-control.service, /usr/bin/systemctl restart thermal-control.service, /usr/bin/systemctl is-active thermal-control.service
EOF
sudo chmod 440 "$SUDOERS_FILE"
sudo visudo -cf "$SUDOERS_FILE"

echo "=== Activation optionnelle au démarrage ==="
sudo systemctl enable thermal-control.service

echo "=== Test status ==="
systemctl is-active thermal-control.service || true

echo ""
echo "Installation terminée."
echo "Commandes utiles:"
echo "  sudo systemctl start thermal-control.service"
echo "  sudo systemctl stop thermal-control.service"
echo "  sudo systemctl restart thermal-control.service"
echo "  systemctl is-active thermal-control.service"
echo "  journalctl -u thermal-control.service -f"
