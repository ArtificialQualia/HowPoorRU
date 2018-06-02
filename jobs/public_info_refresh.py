from jobs import shared
from jobs.shared import logger

from datetime import timezone
from app.flask_shared_modules import rq

@rq.job
def update_all_public_info():
    try:
        logger.debug('start public info refresh')
    
        entity_cursor = shared.db.entities.find({})
        for entity_doc in entity_cursor:
            if 'type' not in entity_doc:
                logger.error('DB entry ' + entity_doc.id + ' does not have a type')
                continue
            elif entity_doc['type'] == 'character':
                user_update(entity_doc['id'])
            elif entity_doc['type'] == 'corporation':
                corp_update(entity_doc['id'])
            elif entity_doc['type'] == 'alliance':
                alliance_update(entity_doc['id'])
    
        logger.debug('done public info refresh')
    except Exception as e:
        logger.exception(e)
        return
        
def user_update(character_id):
    data_to_update = {}
    data_to_remove = None
    op = shared.esiapp.op['get_characters_character_id'](
        character_id=character_id
    )
    public_data = shared.esiclient.request(op)
    if public_data.status != 200:
        logger.error('status: ' + str(public_data.status) + ' error with getting public data: ' + str(public_data.data))
        logger.error('character with issue: ' + str(character_id))
        return
    data_to_update['name'] = public_data.data['name']
    data_to_update['birthday'] = public_data.data['birthday'].v.replace(tzinfo=timezone.utc).strftime("%Y-%m-%d %X")
    data_to_update['corporation_id'] = public_data.data['corporation_id']
    shared.decode_party_id(data_to_update['corporation_id'])
    if 'alliance_id' in public_data.data:
        data_to_update['alliance_id'] = public_data.data['alliance_id']
        shared.decode_party_id(data_to_update['alliance_id'])
    else:
        data_to_remove = {'alliance_id': 1}
    
    character_filter = {'id': character_id}
    update = {"$set": data_to_update}
    if data_to_remove:
        update['$unset'] = data_to_remove
    shared.db.entities.update_one(character_filter, update)
        
def corp_update(corporation_id):
    data_to_update = {}
    data_to_remove = None
    op = shared.esiapp.op['get_corporations_corporation_id'](
        corporation_id=corporation_id
    )
    public_data = shared.esiclient.request(op)
    if public_data.status != 200:
        logger.error('status: ' + str(public_data.status) + ' error with getting public data: ' + str(public_data.data))
        logger.error('corp with issue: ' + str(corporation_id))
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
    else:
        data_to_remove = {'alliance_id': 1}
    if 'date_founded' in public_data.data:
        data_to_update['date_founded'] = public_data.data['date_founded'].v.replace(tzinfo=timezone.utc).strftime("%Y-%m-%d %X")
    
    corporation_filter = {'id': corporation_id}
    update = {"$set": data_to_update}
    if data_to_remove:
        update['$unset'] = data_to_remove
    shared.db.entities.update_one(corporation_filter, update)
    del data_to_update
        
def alliance_update(alliance_id):
    data_to_update = {}
    op = shared.esiapp.op['get_alliances_alliance_id'](
        alliance_id=alliance_id
    )
    public_data = shared.esiclient.request(op)
    if public_data.status != 200:
        logger.error('status: ' + str(public_data.status) + ' error with getting public data: ' + str(public_data.data))
        logger.error('alliance with issue: ' + str(alliance_id))
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
        logger.error('status: ' + str(public_data.status) + ' error with getting public data: ' + str(public_data.data))
        return
    for corp in public_data.data:
        shared.decode_party_id(corp)
    data_to_update['corps'] = public_data.data
    
    alliance_filter = {'id': alliance_id}
    update = {"$set": data_to_update}
    shared.db.entities.update_one(alliance_filter, update)
