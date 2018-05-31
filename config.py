# -*- encoding: utf-8 -*-
import datetime
import logging

# -----------------------------------------------------
# Application configurations
# ------------------------------------------------------
SECRET_KEY = 'REPLACE ME'
PORT = 5015
HOST = 'localhost'
PAGE_SIZE = 25

# -----------------------------------------------------
# MongoDB Configs
# -----------------------------------------------------
MONGO_HOST = 'localhost'
MONGO_PORT = 27017
MONGO_DBNAME = 'howpoorru'
MONGO_CONNECT = False

# -----------------------------------------------------
# ESI Configs
# -----------------------------------------------------
ESI_DATASOURCE = 'tranquility'  # Change it to 'singularity' to use the test server
ESI_SWAGGER_JSON = 'https://esi.tech.ccp.is/latest/swagger.json?datasource=%s' % ESI_DATASOURCE
ESI_SECRET_KEY = 'REPLACE ME'  # your secret key
ESI_CLIENT_ID = 'REPLACE ME'  # your client ID
ESI_CALLBACK = 'http://%s:%d/sso/callback' % (HOST, PORT)  # the callback URI you gave CCP
ESI_USER_AGENT = 'HowPoorRU by Demogorgon Asmodeous'

# ------------------------------------------------------
# Session settings for flask login
# ------------------------------------------------------
PERMANENT_SESSION_LIFETIME = datetime.timedelta(days=30)

# -----------------------------------------------------
# Job Configs (background processing)
# -----------------------------------------------------
JOB_LOG_LEVEL = logging.INFO
RQ_SCHEDULER_INTERVAL = 10
