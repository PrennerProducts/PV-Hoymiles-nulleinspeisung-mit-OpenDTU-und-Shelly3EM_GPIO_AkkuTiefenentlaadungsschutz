#!/usr/bin/env python3
import requests, time, sys
from requests.auth import HTTPBasicAuth
import RPi.GPIO as GPIO #(pip install RPi.GPIO)


# Diese Daten müssen angepasst werden:
serial = "112100000000" # Seriennummer des Hoymiles Wechselrichters
maximum_wr = 300 # Maximale Ausgabe des Wechselrichters
minimum_wr = 100 # Minimale Ausgabe des Wechselrichters

dtu_ip = '192.100.100.20' # IP Adresse von OpenDTU
dtu_nutzer = 'admin' # OpenDTU Nutzername
dtu_passwort = 'openDTU42' # OpenDTU Passwort

shelly_ip = '192.100.100.30' # IP Adresse von Shelly 3EM

# GPIO Initialisierung
GPIO.setmode(GPIO.BCM)                               # Setzen Sie den Modus auf BCM, um die GPIO-Nummerierung zu verwenden
# GPIO.setmode(GPIO.BOARD)                           # Alternativ BOARD-Modus verwendet Physische Pinnummerierung          
PIN = 17                                             # GPIO Pin 
GPIO.setup(PIN, GPIO.IN, pull_up_down=GPIO.PUD_DOWN) # Pin als Eingang konfigurieren
previous_gpio_state = GPIO.LOW  # Nehmen wir an, dass der Startzustand LOW ist

# Überprüfen, ob der Pin HIGH ist
def is_relay_high():
    return GPIO.input(PIN) == GPIO.HIGH


# RestApi OpenDTU Hoymails Power An/Aus
def SetHoymilesPowerStatusOpenDTU(serial, akkuVoltageOK):
    url = f"http://{dtu_ip}/api/power/config"
    data = f'''data={{"serial":"{serial}", "power":{int(akkuVoltageOK)}}}'''  
    headers = {'Content-Type': 'application/x-www-form-urlencoded'}
    auth = HTTPBasicAuth(dtu_nutzer, dtu_passwort)
    
    response = requests.post(url, data=data, auth=auth, headers=headers)
   
   # Überprüfe den Status code der Antwort (200 = 0k)
    try:
        if response.status_code != 200:
            # Versuch, die Antwort als JSON zu interpretieren
            try:
                error_info = response.json()
                error_message = error_info.get("message", "Unbekannter Fehler")
            except:
                # Falls die Antwort nicht als JSON interpretiert werden kann, verwenden wir einfach den Textinhalt
                error_message = response.text
            print(f'Fehler beim Senden des Power Status an OpenDTU. Status Code: {response.status_code}, Antwort: {error_message}')
    except Exception as e:
        print(f'Ein Fehler ist aufgetreten: {e}')

try:
    while True:
        try:
            # Nimmt Daten von der openDTU Rest-API und übersetzt sie in ein json-Format
            r = requests.get(url = f'http://{dtu_ip}/api/livedata/status/inverters' ).json()

            # Selektiert spezifische Daten aus der json response
            reachable   = r['inverters'][0]['reachable'] # Ist DTU erreichbar?
            producing   = int(r['inverters'][0]['producing']) # Produziert der Wechselrichter etwas?
            altes_limit = int(r['inverters'][0]['limit_absolute']) # Altes Limit
            power_dc    = r['inverters'][0]['AC']['0']['Power DC']['v']  # Lieferung DC vom Panel
            power       = r['inverters'][0]['AC']['0']['Power']['v'] # Abgabe BKW AC in Watt
        except:
            print('Fehler beim Abrufen der Daten von openDTU')
        try:
            # Nimmt Daten von der Shelly 3EM Rest-API und übersetzt sie in ein json-Format
            phase_a     = requests.get(f'http://{shelly_ip}/emeter/0', headers={'Content-Type': 'application/json'}).json()['power']
            phase_b     = requests.get(f'http://{shelly_ip}/emeter/1', headers={'Content-Type': 'application/json'}).json()['power']
            phase_c     = requests.get(f'http://{shelly_ip}/emeter/2', headers={'Content-Type': 'application/json'}).json()['power']
            grid_sum    = phase_a + phase_b + phase_c # Aktueller Bezug - rechnet alle Phasen zusammen
        except:
            print('Fehler beim Abrufen der Daten von Shelly 3EM')

        # Werte setzen
        print(f'\nBezug: {round(grid_sum, 1)} W, Produktion: {round(power, 1)} W, Verbrauch: {round(grid_sum + power, 1)} W')
        if reachable:
            setpoint = grid_sum + altes_limit - 5 # Neues Limit in Watt

            # Fange oberes Limit ab
            if setpoint > maximum_wr:
                setpoint = maximum_wr
                print(f'Setpoint auf Maximum: {maximum_wr} W')
            # Fange unteres Limit ab
            elif setpoint < minimum_wr:
                setpoint = minimum_wr
                print(f'Setpoint auf Minimum: {minimum_wr} W')
            else:
                print(f'Setpoint berechnet: {round(grid_sum, 1)} W + {round(altes_limit, 1)} W - 5 W = {round(setpoint, 1)} W')

            if setpoint != altes_limit:
                print(f'Setze Inverterlimit von {round(altes_limit, 1)} W auf {round(setpoint, 1)} W... ', end='')
                # Neues Limit setzen
                try:
                    r = requests.post(
                        url = f'http://{dtu_ip}/api/limit/config',
                        data = f'data={{"serial":"{serial}", "limit_type":0, "limit_value":{setpoint}}}',
                        auth = HTTPBasicAuth(dtu_nutzer, dtu_passwort),
                        headers = {'Content-Type': 'application/x-www-form-urlencoded'}
                    )
                    print(f'Konfiguration gesendet ({r.json()["type"]})')
                except:
                    print('Fehler beim Senden der Konfiguration')
    
    
    # Tiefentladungsschutz checke GPIO Pin ob Akku noch genügend Spannung hat
        current_gpio_state = GPIO.HIGH if is_relay_high() else GPIO.LOW
        
        if current_gpio_state != previous_gpio_state:
            if current_gpio_state == GPIO.HIGH:
                akkuVoltageOK = False
                SetHoymilesPowerStatusOpenDTU(serial, akkuVoltageOK)
                print(f'Akkuspannung zu niedrig, Hoymalis Inverter ist ausgeschaltet, Tiefentladungsschutz aktiviert.')
            else:
                akkuVoltageOK = True
                SetHoymilesPowerStatusOpenDTU(serial, akkuVoltageOK)
                print(f'Akku Voltage OK, Hoymails Inverter ist an.')

            previous_gpio_state = current_gpio_state
            
        sys.stdout.flush() # write out cached messages to stdout
        time.sleep(5) # wait

finally:
    GPIO.cleanup()


