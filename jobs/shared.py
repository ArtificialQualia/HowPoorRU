from pymongo import MongoClient

from esipy import App
from esipy import EsiClient
from esipy import EsiSecurity

import config

import logging
import gc

logger = logging.getLogger('jobs_logger')
logger.setLevel(config.JOB_LOG_LEVEL)
ch = logging.StreamHandler()
ch.setLevel(config.JOB_LOG_LEVEL)
formatter = logging.Formatter('%(asctime)s:%(name)s:%(levelname)s - %(message)s')
ch.setFormatter(formatter)
logger.addHandler(ch)

def initialize_job():
    global db
    global esiapp
    global esisecurity
    global esiclient
    
    db = MongoClient(config.MONGO_HOST, config.MONGO_PORT)[config.MONGO_DBNAME]
    
    # Initialize ESI connection, all three below globals are needed to set up ESI connection
    esiapp = App.create(config.ESI_SWAGGER_JSON)
    
    # init the security object
    esisecurity = EsiSecurity(
        app=esiapp,
        redirect_uri=config.ESI_CALLBACK,
        client_id=config.ESI_CLIENT_ID,
        secret_key=config.ESI_SECRET_KEY,
        headers={'User-Agent': config.ESI_USER_AGENT}
    )
    
    # init the client
    esiclient = EsiClient(
        security=esisecurity,
        cache=None,
        headers={'User-Agent': config.ESI_USER_AGENT}
    )

def cleanup_job():
    global esiclient
    global esisecurity
    global esiapp
    global db
    global logger
    global ch
    global formatter
    del esiclient
    del esisecurity
    del esiapp
    del db
    del logger
    del ch
    del formatter
    gc.collect()

def decode_party_id(party_id):
    id_filter = {'id': party_id}
    result = db.entities.find_one(id_filter)
    if result is not None:
        return
    op = esiapp.op['get_characters_character_id'](
        character_id=party_id
    )
    result = esiclient.request(op)
    if result.status == 200:
        db_entry = {
            'name': result.data['name'],
            'id': party_id,
            'type': 'character'
        }
        db.entities.insert_one(db_entry)
        return
    op = esiapp.op['get_corporations_corporation_id'](
        corporation_id=party_id
    )
    result = esiclient.request(op)
    if result.status == 200:
        db_entry = {
            'name': result.data['name'],
            'id': party_id,
            'type': 'corporation'
        }
        db.entities.insert_one(db_entry)
        return
    op = esiapp.op['get_alliances_alliance_id'](
        alliance_id=party_id
    )
    result = esiclient.request(op)
    if result.status == 200:
        db_entry = {
            'name': result.data['name'],
            'id': party_id,
            'type': 'alliance'
        }
        db.entities.insert_one(db_entry)
        return
    logger.info('No character/corp/alliance found for: ' + str(party_id))
