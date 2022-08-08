#!/usr/bin/python

""" Copyright (c) 2020 Cisco and/or its affiliates.
This software is licensed to you under the terms of the Cisco Sample
Code License, Version 1.1 (the "License"). You may obtain a copy of the
License at
           https://developer.cisco.com/docs/licenses
All use of the material herein must be in accordance with the terms of
the License. All rights not expressly granted by the License are
reserved. Unless required by applicable law or agreed to separately in
writing, software distributed under the License is distributed on an "AS
IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express
or implied. 
"""

import serial
import time
import json
import signal
import threading
import logging
import requests
import os
import datetime

from wsgiref.simple_server import make_server

def _sleep_handler(signum, frame):
    print("SIGINT Received. Stopping CAF")
    raise KeyboardInterrupt

def _stop_handler(signum, frame):
    print("SIGTERM Received. Stopping CAF")
    raise KeyboardInterrupt

signal.signal(signal.SIGTERM, _stop_handler)
signal.signal(signal.SIGINT, _sleep_handler)

PORT = 8000
HOST = "0.0.0.0"

class SerialThread(threading.Thread):
    def __init__(self):
        super(SerialThread, self).__init__()
        self.name = "SerialThread"
        self.setDaemon(True)
        self.stop_event = threading.Event()

    def stop(self):
        self.stop_event.set()

    def run(self):
        INTERVAL = 5 # Interval between publishing in seconds
        URL = "XXX" # URL to post GPS data to

        # Set up serial device
        serial_dev = os.getenv("gps1")
        if serial_dev is None:
            serial_dev="/dev/ttyNMEA1"

        sdev = serial.Serial(port=serial_dev)
        sdev.timeout = 5
        print("Serial:  %s\n", sdev)

        # Set up application logging
        try:
            directory = os.environ['CAF_APP_LOG_DIR'] + "/"
        except KeyError as e:
            directory = "./"
        logger = logging.getLogger('webapp')
        logger.setLevel(logging.INFO)
        file_handler = logging.FileHandler(directory + 'gps_data.log')
        formatter = logging.Formatter('%(msg)s')
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        
        # Main loop
        while True:
            if self.stop_event.is_set():
                break
            quality = None
            no_sattelites = None
            hdop = None
            old_entry = {
                "lat" : "",
                "lon" : ""
            }
            while sdev.inWaiting() > 0:
                time_since = 31
                sensVal = sdev.readline()
                sensVal = sensVal.decode().split(",")
                format = sensVal[0][1:]

                # NMEA data formats: https://anavs.com/knowledgebase/nmea-format/
                if format == "GPGGA":
                    quality = sensVal[6]
                    no_sattelites = sensVal[7]
                    hdop = sensVal[8]
                elif format == "GPRMC" and sensVal[2] == "A" and quality is not None:
                    entry = {
                        "timestamp" : datetime.datetime.now().strftime("%d/%m/%y %H:%M:%SUTC"),
                        "identity" : os.environ["CAF_SYSTEM_NAME"],
                        "lat" : ("" if sensVal[4]=="N" else "-") + sensVal[3][:2] + "." + sensVal[3][2:4] + sensVal[3][5:],
                        "lon" : ("" if sensVal[6]=="E" else "-") + sensVal[5][:2] + "." + sensVal[5][2:5] + sensVal[5][6:],
                        "spd" : f"{float(sensVal[7])*1.852} km/h",
                        "bearing" : f"{sensVal[8]} deg. true",
                        "valid" : "yes",
                        "sattelites" : no_sattelites,
                        "quality" : quality,
                        "hdop" : hdop
                    }
                    
                    if need_to_update(time_since, old_entry, entry):
                        time_since = 0

                        # Log to application files
                        logger.info(json.dumps(entry))

                        # Send to REST endpoint
                        requests.post(URL, headers={"Content-Type" : "application/json"}, json=entry)

                        old_entry = entry
                    else:
                        time_since += INTERVAL

                    time.sleep(INTERVAL)
        sdev.close()

# Check if sending update is necessary
def need_to_update(time_since, old_entry, new_entry):
    if old_entry['lat'] != new_entry['lat'] or old_entry['lon'] != new_entry['lon'] or time_since > 30:
        return True
    return False

def simple_app(environ, start_response):
    status = '200 OK'
    headers = [('Content-type', 'application/json')]
    start_response(status, headers)
    ret = json.dumps({"response" : "OK"})
    return ret

httpd = make_server(HOST, PORT, simple_app)
try:
    p = SerialThread()
    p.start()
    httpd.serve_forever()
except KeyboardInterrupt:
    p.stop()
    httpd.shutdown()