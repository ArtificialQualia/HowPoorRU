from pymongo import MongoClient

from app.flask_shared_modules import esiapp
from app.flask_shared_modules import esiclient
from app.flask_shared_modules import esisecurity

import redis

import config

import logging
from datetime import timezone

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

def user_update(character_id):
    data_to_update = {}
    data_to_update['id'] = character_id
    data_to_update['type'] = 'character'
    data_to_remove = None
    op = esiapp.op['get_characters_character_id'](
        character_id=character_id
    )
    public_data = esiclient.request(op)
    if public_data.status != 200:
        logger.error('status: ' + str(public_data.status) + ' error with getting public data: ' + str(public_data.data))
        logger.error('headers: ' + str(public_data.header))
        logger.error('character with issue: ' + str(character_id))
        return
    data_to_update['name'] = public_data.data['name']
    data_to_update['birthday'] = public_data.data['birthday'].v.replace(tzinfo=timezone.utc).strftime("%Y-%m-%d %X")
    data_to_update['corporation_id'] = public_data.data['corporation_id']
    if 'alliance_id' in public_data.data:
        data_to_update['alliance_id'] = public_data.data['alliance_id']
    else:
        data_to_remove = {'alliance_id': 1}
    
    character_filter = {'id': character_id}
    update = {"$set": data_to_update}
    if data_to_remove:
        update['$unset'] = data_to_remove
    db.entities.update_one(character_filter, update, upsert=True)
    decode_party_id(data_to_update['corporation_id'])
    if 'alliance_id' in public_data.data:
        decode_party_id(data_to_update['alliance_id'])
        
def corp_update(corporation_id):
    data_to_update = {}
    data_to_update['id'] = corporation_id
    data_to_update['type'] = 'corporation'
    data_to_remove = None
    op = esiapp.op['get_corporations_corporation_id'](
        corporation_id=corporation_id
    )
    public_data = esiclient.request(op)
    if public_data.status != 200:
        logger.error('status: ' + str(public_data.status) + ' error with getting public data: ' + str(public_data.data))
        logger.error('headers: ' + str(public_data.header))
        logger.error('corp with issue: ' + str(corporation_id))
        return
    data_to_update['ceo_id'] = public_data.data['ceo_id']
    data_to_update['member_count'] = public_data.data['member_count']
    data_to_update['name'] = public_data.data['name']
    data_to_update['tax_rate'] = public_data.data['tax_rate']
    data_to_update['ticker'] = public_data.data['ticker']
    if 'alliance_id' in public_data.data:
        data_to_update['alliance_id'] = public_data.data['alliance_id']
    else:
        data_to_remove = {'alliance_id': 1}
    if 'date_founded' in public_data.data:
        data_to_update['date_founded'] = public_data.data['date_founded'].v.replace(tzinfo=timezone.utc).strftime("%Y-%m-%d %X")
    
    corporation_filter = {'id': corporation_id}
    update = {"$set": data_to_update}
    if data_to_remove:
        update['$unset'] = data_to_remove
    db.entities.update_one(corporation_filter, update, upsert=True)
    decode_party_id(data_to_update['ceo_id'])
    if 'alliance_id' in public_data.data:
        decode_party_id(data_to_update['alliance_id'])
    del data_to_update
        
def alliance_update(alliance_id):
    data_to_update = {}
    data_to_update['id'] = alliance_id
    data_to_update['type'] = 'alliance'
    op = esiapp.op['get_alliances_alliance_id'](
        alliance_id=alliance_id
    )
    public_data = esiclient.request(op)
    if public_data.status != 200:
        logger.error('status: ' + str(public_data.status) + ' error with getting public data: ' + str(public_data.data))
        logger.error('headers: ' + str(public_data.header))
        logger.error('alliance with issue: ' + str(alliance_id))
        return
    data_to_update['date_founded'] = public_data.data['date_founded'].v.replace(tzinfo=timezone.utc).strftime("%Y-%m-%d %X")
    data_to_update['name'] = public_data.data['name']
    data_to_update['ticker'] = public_data.data['ticker']
    if 'executor_corporation_id' in public_data.data:
        data_to_update['executor_corporation_id'] = public_data.data['executor_corporation_id']
    
    op = esiapp.op['get_alliances_alliance_id_corporations'](
        alliance_id=alliance_id
    )
    public_data = esiclient.request(op)
    if public_data.status != 200:
        logger.error('status: ' + str(public_data.status) + ' error with getting public data: ' + str(public_data.data))
        logger.error('headers: ' + str(public_data.header))
        logger.error('alliance with issue: ' + str(alliance_id))
        return
    data_to_update['corps'] = public_data.data
    
    alliance_filter = {'id': alliance_id}
    update = {"$set": data_to_update}
    db.entities.update_one(alliance_filter, update, upsert=True)
    if 'executor_corporation_id' in public_data.data:
        decode_party_id(data_to_update['executor_corporation_id'])
    for corp in public_data.data:
        decode_party_id(corp)


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
        user_update(party_id)
        return
    op = esiapp.op['get_corporations_corporation_id'](
        corporation_id=party_id
    )
    result = esiclient.request(op)
    if result.status == 200:
        corp_update(party_id)
        return
    op = esiapp.op['get_alliances_alliance_id'](
        alliance_id=party_id
    )
    result = esiclient.request(op)
    if result.status == 200:
        alliance_update(party_id)
        return
    logger.info('No character/corp/alliance found for: ' + str(party_id))
