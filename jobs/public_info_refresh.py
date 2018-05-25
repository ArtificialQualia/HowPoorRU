from jobs import shared

from datetime import datetime
from datetime import timezone

def update_public_info():
    print(datetime.now())
    print('start public info refresh')
    
    shared.initialize_job()
    users_update()
    alliances_update()
    corps_update()
    
    print(datetime.now())
    print('done public info refresh')

def users_update():
    user_cursor = shared.db.users.find({})
    for user_doc in user_cursor:
        data_to_update = {}
        op = shared.esiapp.op['get_characters_character_id'](
            character_id=user_doc['CharacterID']
        )
        public_data = shared.esiclient.request(op)
        if public_data.status != 200:
            print(public_data.data)
            continue
        data_to_update['birthday'] = public_data.data['birthday'].v.replace(tzinfo=timezone.utc).strftime("%Y-%m-%d %X")
        data_to_update['corporation_id'] = public_data.data['corporation_id']
        shared.decode_party_id(data_to_update['corporation_id'])
        if 'alliance_id' in public_data.data:
            data_to_update['alliance_id'] = public_data.data['alliance_id']
            shared.decode_party_id(data_to_update['alliance_id'])
        
        character_filter = {'CharacterID': user_doc['CharacterID']}
        update = {"$set": data_to_update}
        shared.db.users.update_one(character_filter, update)
        
def corps_update():
    corp_cursor = shared.db.corps.find({})
    for corp_doc in corp_cursor:
        data_to_update = {}
        op = shared.esiapp.op['get_corporations_corporation_id'](
            corporation_id=corp_doc['corporation_id']
        )
        public_data = shared.esiclient.request(op)
        if public_data.status != 200:
            print(public_data.data)
            continue
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
            shared.decode_party_id(data_to_update['date_founded'])
        
        corporation_filter = {'corporation_id': corp_doc['corporation_id']}
        update = {"$set": data_to_update}
        shared.db.corps.update_one(corporation_filter, update)
        
def alliances_update():
    alliance_cursor = shared.db.alliances.find({})
    for alliance_doc in alliance_cursor:
        data_to_update = {}
        op = shared.esiapp.op['get_alliances_alliance_id'](
            alliance_id=alliance_doc['alliance_id']
        )
        public_data = shared.esiclient.request(op)
        if public_data.status != 200:
            print(public_data.data)
            continue
        data_to_update['date_founded'] = public_data.data['date_founded'].v.replace(tzinfo=timezone.utc).strftime("%Y-%m-%d %X")
        data_to_update['name'] = public_data.data['name']
        data_to_update['ticker'] = public_data.data['ticker']
        if 'executor_corporation_id' in public_data.data:
            data_to_update['executor_corporation_id'] = public_data.data['executor_corporation_id']
            shared.decode_party_id(data_to_update['executor_corporation_id'])
        
        alliance_filter = {'alliance_id': alliance_doc['alliance_id']}
        update = {"$set": data_to_update}
        shared.db.alliances.update_one(alliance_filter, update)
        
        op = shared.esiapp.op['get_alliances_alliance_id_corporations'](
            alliance_id=alliance_doc['alliance_id']
        )
        public_data = shared.esiclient.request(op)
        if public_data.status != 200:
            print(public_data.data)
            continue
        for corp in public_data.data:
            data_to_update = {'corporation_id': corp}
            corporation_filter = {'corporation_id': corp}
            update = {"$set": data_to_update}
            shared.db.corps.find_one_and_update(corporation_filter, update, upsert=True)