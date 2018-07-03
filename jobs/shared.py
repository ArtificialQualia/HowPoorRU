"""
 contains some shared modules and functions that are used by multiple jobs
 no jobs are run from here, but all jobs import this file
"""

from pymongo import MongoClient
from pymongo import ReturnDocument

from app.flask_shared_modules import esiapp
from app.flask_shared_modules import esiclient
from app.flask_shared_modules import esisecurity

import config

import logging
from datetime import timezone

# setup the logger that is used by all jobs
logger = logging.getLogger('jobs_logger')
logger.setLevel(config.JOB_LOG_LEVEL)
ch = logging.StreamHandler()
ch.setLevel(config.JOB_LOG_LEVEL)
formatter = logging.Formatter('%(asctime)s:%(name)s:%(levelname)s - %(message)s')
ch.setFormatter(formatter)
logger.addHandler(ch)

# setup DB connector manually, as the connector used by routes is only set up after flask is, so it can't be shared
db = MongoClient(config.MONGO_HOST, config.MONGO_PORT, connect=config.MONGO_CONNECT)[config.MONGO_DBNAME]

# convenience references for jobs
esiapp = esiapp
esisecurity = esisecurity
esiclient = esiclient

def user_update(character_id, public_data=None):
    """ adds or updates a DB entry for a user (character) and returns it """
    data_to_update = {}
    data_to_update['id'] = character_id
    data_to_update['type'] = 'character'
    data_to_remove = None
    if not public_data:
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
    new_user_doc = db.entities.find_one_and_update(character_filter, update, upsert=True, return_document=ReturnDocument.AFTER)
    decode_party_id(data_to_update['corporation_id'])
    if 'alliance_id' in public_data.data:
        decode_party_id(data_to_update['alliance_id'])
    return new_user_doc
        
def corp_update(corporation_id, public_data=None):
    """ adds or updates a DB entry for a corporation and returns it """
    data_to_update = {}
    data_to_update['id'] = corporation_id
    data_to_update['type'] = 'corporation'
    data_to_remove = None
    if not public_data:
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
    new_corp_doc = db.entities.find_one_and_update(corporation_filter, update, upsert=True, return_document=ReturnDocument.AFTER)
    decode_party_id(data_to_update['ceo_id'])
    if 'alliance_id' in public_data.data:
        decode_party_id(data_to_update['alliance_id'])
    del data_to_update
    return new_corp_doc
        
def alliance_update(alliance_id, public_data=None):
    """ adds or updates a DB entry for an alliance and returns it """
    data_to_update = {}
    data_to_update['id'] = alliance_id
    data_to_update['type'] = 'alliance'
    if not public_data:
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
    new_alliance_doc = db.entities.find_one_and_update(alliance_filter, update, upsert=True, return_document=ReturnDocument.AFTER)
    if 'executor_corporation_id' in public_data.data:
        decode_party_id(data_to_update['executor_corporation_id'])
    for corp in public_data.data:
        decode_party_id(corp)
    return new_alliance_doc


def decode_party_id(party_id):
    """ function to handle 'unknown' party_ids.  The search endpoint could also be used but there are only a few party types """
    if party_id <= 2:
        return
    id_filter = {'id': party_id}
    result = db.entities.find_one(id_filter)
    if result is not None:
        return result
    op = esiapp.op['get_characters_character_id'](
        character_id=party_id
    )
    result = esiclient.request(op)
    if result.status == 200:
        return user_update(party_id, result)
    op = esiapp.op['get_corporations_corporation_id'](
        corporation_id=party_id
    )
    result = esiclient.request(op)
    if result.status == 200:
        return corp_update(party_id, result)
    op = esiapp.op['get_alliances_alliance_id'](
        alliance_id=party_id
    )
    result = esiclient.request(op)
    if result.status == 200:
        return alliance_update(party_id, result)
    # sometimes the party_id is a '''''''special''''''' value, so most of the time this is no big deal (but could mean error)
    logger.info('No character/corp/alliance found for: ' + str(party_id))
