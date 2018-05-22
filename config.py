# -*- encoding: utf-8 -*-
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.executors.pool import ProcessPoolExecutor
from flask_apscheduler.auth import HTTPBasicAuth
import datetime

# -----------------------------------------------------
# Application configurations
# ------------------------------------------------------
SECRET_KEY = 'REPLACE ME'
PORT = 5015
HOST = 'localhost'

# -----------------------------------------------------
# MongoDB Configs
# -----------------------------------------------------
MONGO_HOST = 'localhost'
MONGO_PORT = 27017
MONGO_DBNAME = 'howpoorru'
#MONGO_CONNECT = False

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
# APScheduler Configs
# -----------------------------------------------------
JOBS = [
        {
            'id': 'process_wallets',
            'func': 'jobs.wallet_refresh:process_wallets',
            'trigger': 'interval',
            'seconds': 120
        }
    ]

SCHEDULER_JOBSTORES = {
    'default': MemoryJobStore()
}

SCHEDULER_EXECUTORS = {
    'default': ProcessPoolExecutor(5)
}

SCHEDULER_JOB_DEFAULTS = {
    'coalesce': True,
    'max_instances': 1
}

SCHEDULER_AUTH = HTTPBasicAuth()
SCHEDULER_AUTH_USER = 'REPLACE ME'
SCHEDULER_AUTH_PASSWORD = 'REPLACE ME'
SCHEDULER_API_ENABLED = True