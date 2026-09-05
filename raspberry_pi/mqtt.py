import time
import pickle
import numpy as np
import RPi.GPIO as GPIO
import board
import adafruit_dht
import json
import paho.mqtt.client as mqtt

try:
    from tflite_runtime.interpreter import Interpreter
except ImportError:
    from tensorflow.lite.python.interpreter import Interpreter


print("Initialisation du systeme de controle IA...")


# ==========================================
# 0. Configuration MQTT - Compatible Superviseur
# ==========================================
MQTT_BROKER = "localhost"
MQTT_PORT = 1883

MQTT_TOPIC_DATA = "thermal_box/data"

MQTT_TOPIC_SETPOINT = "thermal_box/control/setpoint"
MQTT_TOPIC_MODE = "thermal_box/control/mode"
MQTT_TOPIC_MANUAL = "thermal_box/control/manual_power"
MQTT_TOPIC_APPLY = "thermal_box/control/apply"

PERIODE_MQTT = 2.0

client_mqtt = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, "RaspberryPi_NNMPC")

try:
    client_mqtt.connect(MQTT_BROKER, MQTT_PORT)
    client_mqtt.loop_start()
    print("-> Connecte au Broker MQTT local avec succes.")
except Exception as e:
    print(f"-> Attention: Impossible de se connecter a MQTT ({e})")

dernier_envoi_mqtt = 0


# ==========================================
# 1. Configuration du Hardware
# ==========================================
PIN_CHAUFFAGE = 25

dhtDevice = adafruit_dht.DHT22(board.D4)

GPIO.setmode(GPIO.BCM)
GPIO.setup(PIN_CHAUFFAGE, GPIO.OUT)
GPIO.output(PIN_CHAUFFAGE, GPIO.LOW)


# ==========================================
# 2. Chargement de l'IA
# ==========================================
with open("scaler.pkl", "rb") as f:
    scaler = pickle.load(f)

interpreter = Interpreter(model_path="modele_thermique.tflite")
interpreter.allocate_tensors()

input_details = interpreter.get_input_details()
output_details = interpreter.get_output_details()


# ==========================================
# 3. Parametres
# ==========================================
CONSIGNE = 24.0
MODE = "auto"
COMMANDE_MANUELLE = 0.0


# ==========================================
# 4. MQTT - Reception commandes dashboard
# ==========================================
def on_message(client, userdata, msg):
    global CONSIGNE, MODE, COMMANDE_MANUELLE

    topic = msg.topic
    payload = msg.payload.decode()

    try:
        if topic == MQTT_TOPIC_SETPOINT:
            CONSIGNE = float(payload)
            print(f"\n>>> [MQTT] Consigne -> {CONSIGNE} C <<<")

        elif topic == MQTT_TOPIC_MODE:
            mode_recu = payload.lower()

            if mode_recu in ["auto", "manual", "schedule"]:
                MODE = mode_recu
                print(f"\n>>> [MQTT] Mode -> {MODE.upper()} <<<")
            else:
                print(f"Erreur : Mode '{payload}' inconnu.")

        elif topic == MQTT_TOPIC_MANUAL:
            COMMANDE_MANUELLE = float(payload) / 100.0
            COMMANDE_MANUELLE = max(0.0, min(1.0, COMMANDE_MANUELLE))
            print(f"\n>>> [MQTT] Puissance manuelle -> {COMMANDE_MANUELLE * 100:.1f}% <<<")

        elif topic == MQTT_TOPIC_APPLY:
            data = json.loads(payload)

            if "setpoint" in data:
                CONSIGNE = float(data["setpoint"])

            if "mode" in data:
                mode_recu = str(data["mode"]).lower()

                if mode_recu in ["auto", "manual", "schedule"]:
                    MODE = mode_recu

            if "manual_power" in data:
                COMMANDE_MANUELLE = float(data["manual_power"]) / 100.0
                COMMANDE_MANUELLE = max(0.0, min(1.0, COMMANDE_MANUELLE))

            print(
                f"\n>>> [MQTT APPLY] Mode={MODE.upper()} | "
                f"Consigne={CONSIGNE} C | "
                f"Manuel={COMMANDE_MANUELLE * 100:.1f}% <<<"
            )

    except Exception as e:
        print(f"Erreur MQTT commande : {e}")


client_mqtt.on_message = on_message

client_mqtt.subscribe([
    (MQTT_TOPIC_SETPOINT, 0),
    (MQTT_TOPIC_MODE, 0),
    (MQTT_TOPIC_MANUAL, 0),
    (MQTT_TOPIC_APPLY, 0)
])


# ==========================================
# 5. Lecture capteur
# ==========================================
def lire_capteur():
    for _ in range(3):
        try:
            temp = dhtDevice.temperature
            hum = dhtDevice.humidity

            if temp is not None and hum is not None:
                return hum, temp

        except RuntimeError:
            time.sleep(2.0)
            continue

        except Exception as error:
            dhtDevice.exit()
            raise error

    return None, None


humidite, temp_actuelle = lire_capteur()

if temp_actuelle is None:
    temp_actuelle = 20.0

if humidite is None:
    humidite = 50.0

temp_t1 = temp_actuelle
temp_t2 = temp_actuelle

print(f"Demarrage de la regulation. Consigne : {CONSIGNE} C")
print("-" * 50)


# ==========================================
# 6. Boucle principale temps reel
# ==========================================
try:
    while True:

        hum, temp = lire_capteur()

        if temp is not None and hum is not None:
            temp_actuelle = temp
            humidite = hum
            sensor_status = "OK"
        else:
            print("Erreur capteur, on garde les anciennes valeurs.")
            sensor_status = "ERROR"

        # ==========================================
        # Controle AUTO / SCHEDULE avec NN-MPC
        # ==========================================
        if MODE == "auto" or MODE == "schedule":

            entrees = np.array([
                [temp_actuelle, CONSIGNE, humidite, temp_t1, temp_t2]
            ])

            entrees_scaled = scaler.transform(entrees).astype(np.float32)

            interpreter.set_tensor(input_details[0]["index"], entrees_scaled)
            interpreter.invoke()

            commande_predite = interpreter.get_tensor(output_details[0]["index"])[0][0]
            commande_predite = max(0.0, min(1.0, float(commande_predite)))

            if temp_actuelle > CONSIGNE:
                commande_predite = 0.0

            mode_affichage = MODE.upper()
            controller_name = "NN-MPC"

        else:
            commande_predite = COMMANDE_MANUELLE
            mode_affichage = "MANUAL"
            controller_name = "MANUAL"

        pourcentage = round(float(commande_predite * 100), 3)

        print(
            f"[{mode_affichage}] "
            f"Temp: {temp_actuelle:.1f} C | "
            f"Hum: {humidite:.1f}% | "
            f"Consigne: {CONSIGNE} C -> "
            f"Commande: {pourcentage:.3f}%"
        )

        # ==========================================
        # MQTT - Envoi JSON vers superviseur Node-RED
        # ==========================================
        temps_actuel = time.time()

        if (temps_actuel - dernier_envoi_mqtt) >= PERIODE_MQTT:

            payload_mqtt = {
                "temperature": round(float(temp_actuelle), 2),
                "humidity": round(float(humidite), 2),
                "setpoint": round(float(CONSIGNE), 2),
                "command": round(float(pourcentage), 3),
                "mode": MODE.upper(),
                "controller": controller_name,
                "mqtt": "Connected",
                "sensor": sensor_status,
                "influx": "OK",
                "alert": "SURCHAUFFE" if temp_actuelle > CONSIGNE + 5 else "NORMAL",
                "pwm_period": 1.0,
                "pwm_on": round(float(commande_predite), 3),
                "pwm_off": round(float(1.0 - commande_predite), 3),
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
            }

            client_mqtt.publish(MQTT_TOPIC_DATA, json.dumps(payload_mqtt))
            dernier_envoi_mqtt = temps_actuel

        # ==========================================
        # Slow PWM - periode 1 seconde
        # ==========================================
        temps_on = float(commande_predite)
        temps_off = float(1.0 - commande_predite)

        if temps_on > 0:
            GPIO.output(PIN_CHAUFFAGE, GPIO.HIGH)
            time.sleep(temps_on)

        if temps_off > 0:
            GPIO.output(PIN_CHAUFFAGE, GPIO.LOW)
            time.sleep(temps_off)

        temp_t2 = temp_t1
        temp_t1 = temp_actuelle


except KeyboardInterrupt:
    print("\nArret de la regulation.")


finally:
    GPIO.output(PIN_CHAUFFAGE, GPIO.LOW)
    GPIO.cleanup()
    dhtDevice.exit()

    client_mqtt.loop_stop()
    client_mqtt.disconnect()

    print("Systeme eteint proprement.")