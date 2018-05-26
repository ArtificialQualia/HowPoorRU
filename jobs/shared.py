from pymongo import MongoClient

from esipy import App
from esipy import EsiClient
from esipy import EsiSecurity

from urllib import error

import config

import logging

logger = logging.getLogger('jobs_logger')
logger.setLevel(config.SCHEDULER_LOG_LEVEL)
ch = logging.StreamHandler()
ch.setLevel(config.SCHEDULER_LOG_LEVEL)
formatter = logging.Formatter('%(asctime)s:%(name)s:%(levelname)s - %(message)s')
ch.setFormatter(formatter)
logger.addHandler(ch)

def initialize_job():
    global db
    global esiapp
    global esisecurity
    global esiclient
    
    db = MongoClient(config.MONGO_HOST, config.MONGO_PORT)[config.MONGO_DBNAME]
    
    try:
        esiapp = App.create(config.ESI_SWAGGER_JSON)
    except error.HTTPError as e:
        logger.error(e)
        return
    
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

def decode_party_id(party_id):
    character_filter = {'CharacterID': party_id}
    corp_filter = {'corporation_id': party_id}
    alliance_filter = {'alliance_id': party_id}
    result = db.users.find_one(character_filter)
    if result is not None:
        return
    result = db.corporations.find_one(corp_filter)
    if result is not None:
        return
    result = db.alliances.find_one(alliance_filter)
    if result is not None:
        return
    op = esiapp.op['get_characters_character_id'](
        character_id=party_id
    )
    result = esiclient.request(op)
    if result.status == 200:
        db_entry = {
            'CharacterName': result.data['name'],
            'CharacterID': party_id
        }
        db.users.insert_one(db_entry)
        return
    op = esiapp.op['get_corporations_corporation_id'](
        corporation_id=party_id
    )
    result = esiclient.request(op)
    if result.status == 200:
        db_entry = {
            'name': result.data['name'],
            'corporation_id': party_id
        }
        db.corporations.insert_one(db_entry)
        return
    op = esiapp.op['get_alliances_alliance_id'](
        alliance_id=party_id
    )
    result = esiclient.request(op)
    if result.status == 200:
        db_entry = {
            'name': result.data['name'],
            'alliance_id': party_id
        }
        db.alliances.insert_one(db_entry)
        return
    logger.info('No character/corp/alliance found for: ' + str(party_id))