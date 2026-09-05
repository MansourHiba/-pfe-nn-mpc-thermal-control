# 🌡️ Commande intelligente d'un système thermique par NN-MPC et IoT

**Projet de Fin d'Études — ISITCom, Université de Sousse (2023–2026)**
Réalisé au LACS, ENIT, Tunis — févr. à mai 2026

## 🎯 Objectif

Réguler automatiquement la température d'une maquette thermique en remplaçant un contrôleur **MPC (Model Predictive Control)** — trop coûteux en calcul pour une carte embarquée — par un **réseau de neurones (NN-MPC)** qui reproduit sa stratégie de commande, tout en restant exécutable en temps réel sur un Raspberry Pi.

## 🏗️ Architecture du projet

```
┌─────────────┐     ┌──────────────────┐     ┌────────────────────┐
│   GEKKO     │ --> │   TensorFlow      │ --> │  TensorFlow Lite    │
│  MPC expert │     │  Entraînement NN  │     │  Déploiement embarqué│
│ (génération │     │  (reproduit le    │     │  sur Raspberry Pi 4 │
│  dataset)   │     │   comportement    │     │                     │
│             │     │   du MPC)         │     │                     │
└─────────────┘     └──────────────────┘     └──────────┬──────────┘
                                                          │
                                              ┌───────────▼───────────┐
                                              │   Capteur DHT22        │
                                              │   + Relais SSR (PWM)   │
                                              └───────────┬───────────┘
                                                          │
                                    ┌─────────────────────▼─────────────────────┐
                                    │   MQTT → Node-RED → InfluxDB → Grafana     │
                                    │   (supervision, historisation, dashboard)  │
                                    └─────────────────────────────────────────────┘
```

## 📂 Structure du dépôt

```
├── notebook/
│   └── code.ipynb              # Génération du dataset (GEKKO) + entraînement du NN (TensorFlow)
├── raspberry_pi/
│   ├── mqtt.py                 # Script principal : contrôle temps réel + communication MQTT
│   ├── modele_thermique.tflite # Modèle NN-MPC converti pour l'embarqué
│   ├── scaler.pkl              # Normalisation des données d'entrée
│   └── systemd/
│       ├── thermal-control.service          # Unité systemd du service
│       └── setup_thermal_control_service.sh # Script d'installation automatique du service
├── data/
│   └── data_expert_parfaite.csv # Dataset généré par le MPC expert (GEKKO)
└── docs/
    └── rapport_pfe.pdf          # Rapport complet du PFE (116 pages)
```

## ⚙️ Fonctionnement

1. **Génération de données** (`notebook/code.ipynb`, partie 1) : un contrôleur MPC de référence est simulé avec **GEKKO** pour produire un dataset "expert" reliant l'état du système (température, consigne, humidité, historique) à la commande de chauffage optimale.
2. **Entraînement du NN-MPC** (`notebook/code.ipynb`, partie 2) : un réseau de neurones (Keras/TensorFlow) apprend à reproduire cette stratégie de commande.
3. **Conversion embarquée** : le modèle est converti en **TensorFlow Lite** pour tourner efficacement sur Raspberry Pi.
4. **Contrôle temps réel** (`raspberry_pi/mqtt.py`) :
   - Lecture du capteur **DHT22** (température/humidité)
   - Inférence du modèle NN-MPC pour prédire la commande optimale
   - Pilotage du chauffage via un relais **SSR** en PWM lente
   - Publication des mesures et de l'état du système via **MQTT** vers Node-RED
5. **Supervision IoT** : Node-RED reçoit les données, permet de modifier la consigne à distance, les historise dans **InfluxDB** et les visualise dans **Grafana**.
6. **Déploiement en service** : `setup_thermal_control_service.sh` installe `mqtt.py` comme service **systemd**, garantissant un démarrage automatique et un redémarrage en cas d'erreur.

## 🧠 Architecture du réseau de neurones (NN-MPC)

Un perceptron multicouche (MLP) compact, entraîné pour approximer la loi de commande du MPC de référence :

| Couche | Type | Activation | Neurones | Paramètres |
|--------|------|------------|----------|------------|
| Entrée | Dense | — | 5 | — |
| Cachée 1 | Dense | ReLU | 32 | 192 |
| Dropout | Dropout (0.2) | — | — | 0 |
| Cachée 2 | Dense | ReLU | 16 | 528 |
| Dropout | Dropout (0.2) | — | — | 0 |
| Cachée 3 | Dense | ReLU | 8 | 136 |
| Sortie | Dense | Sigmoid | 1 | 9 |

**865 paramètres entraînables** au total — volontairement compact pour tourner en temps réel sur Raspberry Pi.

**Entrées du modèle** : température actuelle, consigne, humidité, température à t-1, température à t-2
**Sortie** : commande de chauffage normalisée [0,1] → convertie en % de puissance PWM

**Entraînement** : optimiseur Adam (lr=0.001), perte MSE, batch size 32, 200 époques max avec early stopping (patience 15), split 70/15/15 (train/val/test).

## 📊 Résultats obtenus

**Qualité de la prédiction NN-MPC** (vs commande MPC de référence, sur l'ensemble de test) :

| Métrique | Keras (.h5) | TFLite (.tflite) |
|---|---|---|
| R² | 98,06 % | 98,06 % |
| Taille du modèle | 48,96 KB | **5,78 KB** |
| Temps d'inférence (Raspberry Pi 4) | ≈ 0,20 ms | **≈ 0,015 ms** |
| RAM utilisée | ~10–20 MB | ~2–5 MB |
| CPU utilisé | – | ~1–3 % |

**Validation du modèle thermique identifié** : R² = 95,22 %, RMSE = 1,22 °C (réponse simulée vs mesurée, échelon à 60 %).

**Comparaison expérimentale PID vs MPC vs NN-MPC** (consigne 30 °C, sur maquette réelle) :

| Métrique | PID | MPC | NN-MPC | Meilleur |
|---|---|---|---|---|
| Dépassement (%) | 1,33 | 0,67 | **0,33** | NN-MPC |
| Temps de montée (s) | 148,86 | 96,98 | **92,57** | NN-MPC |
| Temps de stabilisation (s) | 189,20 | 117,03 | **110,37** | NN-MPC |
| Erreur statique (°C) | 0,276 | 0,123 | **0,045** | NN-MPC |
| MAE (°C) | 0,791 | 0,468 | **0,419** | NN-MPC |
| Indice énergétique (%) | 100,0 | 98,7 | **97,3** | NN-MPC |

Le NN-MPC reproduit fidèlement la stratégie du MPC de référence tout en étant ~13× plus léger et ~13× plus rapide à l'inférence — et il surpasse le PID classique sur presque tous les critères.

**Robustesse — rejet de perturbation** (ouverture temporaire de l'enceinte, consigne 30 °C) :

| Métrique | PID | MPC | NN-MPC |
|---|---|---|---|
| Déviation max (°C) | 0,60 | 0,40 | **0,30** |
| Temps de récupération | ≈ 83,5 s | ≈ 61,0 s | **≈ 31,8 s** |

**Suivi multi-consignes** (25 à 35 °C) : dépassement moyen 0,336 %, erreur statique moyenne 0,061 °C — le modèle généralise bien sur toute la plage de fonctionnement.

## 🔬 Matériel utilisé

- Raspberry Pi 4 (unité de traitement embarquée)
- Capteur DHT22 (température & humidité)
- Relais statique SSR (pilotage de la lampe en PWM)
- Lampe incandescente (élément chauffant de la maquette)
- Enceinte thermique expérimentale

## 🔌 Modes de fonctionnement (contrôlables via MQTT)

| Mode | Description |
|------|-------------|
| `auto` | Commande calculée par le modèle NN-MPC |
| `schedule` | Comme `auto`, piloté par une programmation horaire côté Node-RED |
| `manual` | Puissance de chauffage fixée manuellement (0–100%) |

Topics MQTT utilisés : `thermal_box/data`, `thermal_box/control/setpoint`, `thermal_box/control/mode`, `thermal_box/control/manual_power`, `thermal_box/control/apply`.

## 🛠️ Stack technique

- **IA/Modélisation** : GEKKO, TensorFlow, Keras, TensorFlow Lite
- **Embarqué** : Raspberry Pi 4, RPi.GPIO, DHT22, relais SSR
- **IoT/Supervision** : MQTT (paho-mqtt), Node-RED, InfluxDB, Grafana
- **Système** : systemd (service Linux)

## 🚀 Installation sur Raspberry Pi

```bash
# Copier le dossier raspberry_pi/ sur la carte, par ex. dans /home/pi/Desktop/test_final
cd raspberry_pi
pip install -r requirements.txt

# Installer le service (démarrage auto + redémarrage en cas d'erreur)
chmod +x systemd/setup_thermal_control_service.sh
./systemd/setup_thermal_control_service.sh

# Commandes utiles
sudo systemctl start thermal-control.service
sudo systemctl status thermal-control.service
journalctl -u thermal-control.service -f
```

## 📄 Documentation complète

Le rapport détaillé (analyse, modélisation, UML, implémentation, résultats complets) est disponible dans [`docs/rapport_pfe.pdf`](docs/rapport_pfe.pdf).

## 👤 Auteure

**Hiba Ben Mansour** — Licence en ingénierie des systèmes informatiques, spécialité systèmes embarqués & IoT
[LinkedIn](https://linkedin.com/in/hiba-ben-mansour-b45a372b4) • [GitHub](https://github.com/MansourHiba)
