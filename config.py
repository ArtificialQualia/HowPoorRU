# -*- encoding: utf-8 -*-
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.executors.pool import ProcessPoolExecutor
from flask_apscheduler.auth import HTTPBasicAuth
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
        },
        {
            'id': 'update_all_public_info',
            'func': 'jobs.public_info_refresh:update_all_public_info',
            'trigger': 'interval',
            'seconds': 3600
        }
    ]

SCHEDULER_JOBSTORES = {
    'default': MemoryJobStore()
}

SCHEDULER_EXECUTORS = {
    'default': ProcessPoolExecutor(10)
}

SCHEDULER_JOB_DEFAULTS = {
    'coalesce': True,
    'max_instances': 1,
    'misfire_grace_time': 5
}

SCHEDULER_AUTH = HTTPBasicAuth()
SCHEDULER_AUTH_USER = 'REPLACE ME'
SCHEDULER_AUTH_PASSWORD = 'REPLACE ME'
SCHEDULER_API_ENABLED = True
SCHEDULER_LOG_LEVEL = logging.DEBUG