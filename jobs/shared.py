from pymongo import MongoClient

from app.flask_shared_modules import esiapp
from app.flask_shared_modules import esiclient
from app.flask_shared_modules import esisecurity

import config

import logging

logger = logging.getLogger('jobs_logger')
logger.setLevel(config.JOB_LOG_LEVEL)
ch = logging.StreamHandler()
ch.setLevel(config.JOB_LOG_LEVEL)
formatter = logging.Formatter('%(asctime)s:%(name)s:%(levelname)s - %(message)s')
ch.setFormatter(formatter)
logger.addHandler(ch)

db = MongoClient(config.MONGO_HOST, config.MONGO_PORT, connect=config.MONGO_CONNECT)[config.MONGO_DBNAME]

esiapp = esiapp
esisecurity = esisecurity
esiclient = esiclient

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
