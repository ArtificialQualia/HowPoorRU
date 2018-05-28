from jobs import shared
from jobs.shared import logger

from datetime import datetime
from datetime import timezone

def update_all_public_info():
    logger.debug('start public info refresh')
    
    shared.initialize_job()
    users_update()
    alliances_update()
    corps_update()
    
    logger.debug('done public info refresh')

def users_update():
    user_cursor = shared.db.entities.find({})
    for user_doc in user_cursor:
        user_update(user_doc['id'])
        
def user_update(character_id, data_to_update={}):
    op = shared.esiapp.op['get_characters_character_id'](
        character_id=character_id
    )
    public_data = shared.esiclient.request(op)
    if public_data.status != 200:
        logger.error(public_data.data)
        return
    data_to_update['name'] = public_data.data['name']
    data_to_update['birthday'] = public_data.data['birthday'].v.replace(tzinfo=timezone.utc).strftime("%Y-%m-%d %X")
    data_to_update['corporation_id'] = public_data.data['corporation_id']
    shared.decode_party_id(data_to_update['corporation_id'])
    if 'alliance_id' in public_data.data:
        data_to_update['alliance_id'] = public_data.data['alliance_id']
        shared.decode_party_id(data_to_update['alliance_id'])
    
    character_filter = {'id': character_id}
    update = {"$set": data_to_update}
    shared.db.entities.update_one(character_filter, update)
    
        
def corps_update():
    corp_cursor = shared.db.corporations.find({})
    for corp_doc in corp_cursor:
        corp_update(corp_doc['id'])
        
def corp_update(corporation_id, data_to_update={}):
    op = shared.esiapp.op['get_corporations_corporation_id'](
        corporation_id=corporation_id
    )
    public_data = shared.esiclient.request(op)
    if public_data.status != 200:
        logger.error(public_data.data)
        return
    data_to_update['ceo_id'] = public_data.data['ceo_id']
    shared.decode_party_id(data_to_update['ceo_id'])
    data_to_update['member_count'] = public_data.data['member_count']
    data_to_update['name'] = public_data.data['name']
    data_to_update['tax_rate'] = public_data.data['tax_rate']
    data_to_update['ticker'] = public_data.data['ticker']
    if 'alliance_id' in public_data.data:
        data_to_update['alliance_id'] = public_data.data['alliance_id']
        shared.decode_party_id(data_to_update['alliance_id'])
    if 'date_founded' in public_data.data:
        data_to_update['date_founded'] = public_data.data['date_founded'].v.replace(tzinfo=timezone.utc).strftime("%Y-%m-%d %X")
    
    corporation_filter = {'id': corporation_id}
    update = {"$set": data_to_update}
    shared.db.entities.update_one(corporation_filter, update)
        
def alliances_update():
    alliance_cursor = shared.db.alliances.find({})
    for alliance_doc in alliance_cursor:
        alliance_update(alliance_doc['id'])
        
def alliance_update(alliance_id, data_to_update={}):
        op = shared.esiapp.op['get_alliances_alliance_id'](
            alliance_id=alliance_id
        )
        public_data = shared.esiclient.request(op)
        if public_data.status != 200:
            logger.error(public_data.data)
            return
        data_to_update['date_founded'] = public_data.data['date_founded'].v.replace(tzinfo=timezone.utc).strftime("%Y-%m-%d %X")
        data_to_update['name'] = public_data.data['name']
        data_to_update['ticker'] = public_data.data['ticker']
        if 'executor_corporation_id' in public_data.data:
            data_to_update['executor_corporation_id'] = public_data.data['executor_corporation_id']
            shared.decode_party_id(data_to_update['executor_corporation_id'])
        
        op = shared.esiapp.op['get_alliances_alliance_id_corporations'](
            alliance_id=alliance_id
        )
        public_data = shared.esiclient.request(op)
        if public_data.status != 200:
            logger.error(public_data.data)
            return
        for corp in public_data.data:
            shared.decode_party_id(corp)
        data_to_update['corps'] = public_data.data
        
        alliance_filter = {'id': alliance_id}
        update = {"$set": data_to_update}
        shared.db.entities.update_one(alliance_filter, update)