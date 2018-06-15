"""
 Helper file containing the functions needed to process journal's 'context' field
 Note that no actual jobs are run from here, it is used by jobs/wallet_refresh.py
"""

from pymongo import ReturnDocument

from jobs import shared
from jobs.shared import logger

def decode_context_id(journal_entry, entity_doc, division):
    """ entry point for handling context_ids, would look better with a switch but alas this is python """
    # note that that schema used for contexts is totally different from what we get from ESI, a list of dicts is used
    journal_entry['context'] = [{}]
    
    # hopefully the context_id is in the database, otherwise a lot of work must be done to decode it
    id_filter = {'id': journal_entry['context_id']}
    result = shared.db.entities.find_one(id_filter)
    if result:
        journal_entry['context'][0]['id'] = result['id']
        journal_entry['context'][0]['name'] = result['name']
        journal_entry['context'][0]['type'] = result['type']
    elif journal_entry['context_id_type'] == 'character_id':
        result = shared.user_update(journal_entry['context_id'])
        if result:
            journal_entry['context'][0]['id'] = result['id']
            journal_entry['context'][0]['name'] = result['name']
            journal_entry['context'][0]['type'] = result['type']
    elif journal_entry['context_id_type'] == 'corporation_id':
        result = shared.corp_update(journal_entry['context_id'])
        if result:
            journal_entry['context'][0]['id'] = result['id']
            journal_entry['context'][0]['name'] = result['name']
            journal_entry['context'][0]['type'] = result['type']
    elif journal_entry['context_id_type'] == 'system_id':
        result = update_system(journal_entry['context_id'])
        if result:
            journal_entry['context'][0]['id'] = result['id']
            journal_entry['context'][0]['name'] = result['name']
            journal_entry['context'][0]['type'] = result['type']
    # CCPls, sometimes 'eve_system' is actually 'type_id', specifically with ships :(
    elif journal_entry['context_id_type'] == 'eve_system' or journal_entry['context_id_type'] == 'type_id':
        result = update_item(journal_entry['context_id'], 'ship')
        if result:
            journal_entry['context'][0]['id'] = result['id']
            journal_entry['context'][0]['name'] = result['name']
            journal_entry['context'][0]['type'] = result['type']
    # market_transaction_ids are a lot more work to decide and extra contexts must be added, so those are handled separately
    elif journal_entry['context_id_type'] == 'market_transaction_id':
        update_market_transaction(journal_entry, entity_doc, division)
    elif journal_entry['context_id_type'] == 'station_id':
        result = update_station(journal_entry['context_id'])
        if result:
            journal_entry['context'][0]['id'] = result['id']
            journal_entry['context'][0]['name'] = result['name']
            journal_entry['context'][0]['type'] = result['type']
            # type_id is required for stations as their images don't use the regular id like other objects
            journal_entry['context'][0]['type_id'] = result['type_id']
    else:
        journal_entry['context'][0]['id'] = journal_entry['context_id']
        journal_entry['context'][0]['type'] = journal_entry['context_id_type']
        
    del journal_entry['context_id']
    del journal_entry['context_id_type']
    
def update_market_transaction(journal_entry, entity_doc, division):
    """ adds stations (or locations) and item type to market_transaction_ids """
    #CCPls fix bug
    if journal_entry['context_id'] == 1:
        return
    if not division:
        op = shared.esiapp.op['get_characters_character_id_wallet_transactions'](
            character_id=entity_doc['id'],
            from_id=journal_entry['context_id']
        )
    else:
        op = shared.esiapp.op['get_corporations_corporation_id_wallets_division_transactions'](
            corporation_id=entity_doc['id'],
            division=division,
            from_id=journal_entry['context_id']
        )
    public_data = shared.esiclient.request(op)
    if public_data.status != 200:
        logger.error('status: ' + str(public_data.status) + ' error with getting market transaction: ' + str(public_data.data))
        logger.error('headers: ' + str(public_data.header))
        logger.error('entity with error: ' + str(entity_doc['id']))
    else:
        for transaction in public_data.data:
            if transaction['transaction_id'] == journal_entry['context_id']:
                journal_entry['unit_price'] = transaction['unit_price']
                journal_entry['quantity'] = transaction['quantity']
                journal_entry['context'][0]['id'] = journal_entry['context_id']
                journal_entry['context'][0]['type'] = journal_entry['context_id_type']
                journal_entry['context'].append({})
                journal_entry['context'][1]['id'] = transaction['location_id']
                journal_entry['context'][1]['type'] = 'location_id'
                journal_entry['context'].append({})
                journal_entry['context'][2]['id'] = transaction['type_id']
                journal_entry['context'][2]['type'] = 'item'
                id_filter = {'id': transaction['type_id']}
                result = shared.db.entities.find_one(id_filter)
                if result is None:
                    result = update_item(transaction['type_id'], 'item')
                if result:
                    journal_entry['context'][2]['name'] = result['name']
                id_filter = {'id': transaction['location_id']}
                result = shared.db.entities.find_one(id_filter)
                if result is None:
                    result = update_station(transaction['location_id'])
                if result:
                    journal_entry['context'][1]['name'] = result['name']
                    journal_entry['context'][1]['type'] = result['type']
                    journal_entry['context'][1]['type_id'] = result['type_id']
                if journal_entry['ref_type'] == 'market_escrow' and journal_entry['first_party_id'] == journal_entry['second_party_id']:
                    journal_entry['second_party_id'] = transaction['client_id']
                    result = shared.decode_party_id(journal_entry['second_party_id'])
                    if result:
                        journal_entry['second_party_name'] = result['name']
                        journal_entry['second_party_type'] = result['type']
                return
            elif transaction['transaction_id'] < journal_entry['context_id']:
                break
    # if ESI fails or the market_transaction simply isn't in the ESI response,
    # the journal entry is added to a special field so it can be processed on the next journal update
    logger.info('market transaction ID ' + str(journal_entry['context_id']) + ' not found in transaction data, probably bad cache timing.  Will try again later.')
    if division:
        missed_journal_ids = entity_doc.get('missed_market_transactions_' + str(division)) or []
        missed_journal_ids.append(journal_entry['id'])
        entity_doc['missed_market_transactions_' + str(division)] = missed_journal_ids
    else:
        missed_journal_ids = entity_doc.get('missed_market_transactions') or []
        missed_journal_ids.append(journal_entry['id'])
        entity_doc['missed_market_transactions'] = missed_journal_ids
    
def update_station(station_id):
    """ adds a previously unknown station to the DB and returns it """
    data_to_update = {}
    data_to_update['id'] = station_id
    data_to_update['type'] = 'station'
    op = shared.esiapp.op['get_universe_stations_station_id'](
        station_id=station_id
    )
    public_data = shared.esiclient.request(op)
    if public_data.status != 200:
        if public_data.status == 400:
            logger.info('No station found for: ' + str(station_id) + ', it is probably a citadel.')
            return
        logger.error('status: ' + str(public_data.status) + ' error with getting station data: ' + str(public_data.data))
        logger.error('headers: ' + str(public_data.header))
        logger.error('system with error: ' + str(station_id))
        return
    data_to_update['name'] = public_data.data['name']
    data_to_update['type_id'] = public_data.data['type_id']
    data_to_update['system_id'] = public_data.data['system_id']
    
    id_filter = {'id': public_data.data['system_id']}
    result = shared.db.entities.find_one(id_filter)
    if result is None:
        update_system(public_data.data['system_id'])
    
    data_to_update_id = {'id': data_to_update['id']}
    update = {"$set": data_to_update}
    return shared.db.entities.find_one_and_update(data_to_update_id, update, upsert=True, return_document=ReturnDocument.AFTER)
    

def update_system(system_id):
    """ adds a previously unknown system to the DB and returns it """
    data_to_update = {}
    data_to_update['id'] = system_id
    data_to_update['type'] = 'system'
    op = shared.esiapp.op['get_universe_systems_system_id'](
        system_id=system_id
    )
    public_data = shared.esiclient.request(op)
    if public_data.status != 200:
        logger.error('status: ' + str(public_data.status) + ' error with getting system data: ' + str(public_data.data))
        logger.error('headers: ' + str(public_data.header))
        logger.error('system with error: ' + str(system_id))
        return
    data_to_update['name'] = public_data.data['name']
    data_to_update['security_status'] = public_data.data['security_status']
    data_to_update['constellation_id'] = public_data.data['constellation_id']
    if 'stations' in public_data.data:
        data_to_update['stations'] = public_data.data['stations']
    
    id_filter = {'id': public_data.data['constellation_id']}
    result = shared.db.entities.find_one(id_filter)
    if result is None:
        contellation_name, region_name, region_id = update_constellation(public_data.data['constellation_id'])
        if not contellation_name:
            return
        data_to_update['region_name'] = region_name
        data_to_update['region_id'] = region_id
        data_to_update['constellation_name'] = contellation_name
    else:
        data_to_update['constellation_name'] = result['name']
        data_to_update['region_name'] = result['region_name']
        data_to_update['region_id'] = result['region_id']
    
    data_to_update_id = {'id': data_to_update['id']}
    update = {"$set": data_to_update}
    return shared.db.entities.find_one_and_update(data_to_update_id, update, upsert=True, return_document=ReturnDocument.AFTER)

def update_constellation(constellation_id):
    """ adds a previously unknown constellation to the DB and returns it """
    data_to_update = {}
    data_to_update['id'] = constellation_id
    data_to_update['type'] = 'constellation'
    op = shared.esiapp.op['get_universe_constellations_constellation_id'](
        constellation_id=constellation_id
    )
    public_data = shared.esiclient.request(op)
    if public_data.status != 200:
        logger.error('status: ' + str(public_data.status) + ' error with getting constellation data: ' + str(public_data.data))
        logger.error('headers: ' + str(public_data.header))
        logger.error('constellation with error: ' + str(constellation_id))
        return False, False, False
    data_to_update['name'] = public_data.data['name']
    data_to_update['systems'] = public_data.data['systems']
    data_to_update['region_id'] = public_data.data['region_id']
    
    id_filter = {'id': public_data.data['region_id']}
    result = shared.db.entities.find_one(id_filter)
    if result is None:
        region_name = update_region(public_data.data['region_id'])
        if not region_name:
            return False, False, False
        data_to_update['region_name'] = region_name
    else:
        data_to_update['region_name'] = result['name']
    
    data_to_update_id = {'id': data_to_update['id']}
    update = {"$set": data_to_update}
    shared.db.entities.update_one(data_to_update_id, update, upsert=True)
    return data_to_update['name'], data_to_update['region_name'], public_data.data['region_id']

def update_region(region_id):
    """ adds a previously unknown region to the DB and returns it """
    data_to_update = {}
    data_to_update['id'] = region_id
    data_to_update['type'] = 'region'
    op = shared.esiapp.op['get_universe_regions_region_id'](
        region_id=region_id
    )
    public_data = shared.esiclient.request(op)
    if public_data.status != 200:
        logger.error('status: ' + str(public_data.status) + ' error with getting region data: ' + str(public_data.data))
        logger.error('headers: ' + str(public_data.header))
        logger.error('region with error: ' + str(region_id))
        return False
    data_to_update['name'] = public_data.data['name']
    data_to_update['constellations'] = public_data.data['constellations']
    data_to_update['description'] = public_data.data['description']
    
    data_to_update_id = {'id': data_to_update['id']}
    update = {"$set": data_to_update}
    shared.db.entities.update_one(data_to_update_id, update, upsert=True)
    return data_to_update['name']

def update_item(item_id, item_type):
    """ adds a previously unknown item to the DB and returns it """
    data_to_update = {}
    data_to_update['id'] = item_id
    data_to_update['type'] = item_type
    op = shared.esiapp.op['get_universe_types_type_id'](
        type_id=item_id
    )
    public_data = shared.esiclient.request(op)
    if public_data.status != 200:
        if public_data.status == 400:
            logger.info('No item found for: ' + str(item_id) + ', it is probably not an item.')
            return
        logger.error('status: ' + str(public_data.status) + ' error with getting item data: ' + str(public_data.data))
        logger.error('headers: ' + str(public_data.header))
        logger.error('item with error: ' + str(item_id))
        return
    data_to_update['name'] = public_data.data['name']
    data_to_update['group_id'] = public_data.data['group_id']
    
    id_filter = {'id': public_data.data['group_id']}
    result = shared.db.entities.find_one(id_filter)
    if result is None:
        op = shared.esiapp.op['get_universe_groups_group_id'](
            group_id=public_data.data['group_id']
        )
        public_data = shared.esiclient.request(op)
        if public_data.status != 200:
            logger.error('status: ' + str(public_data.status) + ' error with getting group data: ' + str(public_data.data))
            logger.error('headers: ' + str(public_data.header))
            logger.error('group with error: ' + str(public_data.data['group_id']))
            return
        group_data = {}
        group_data['id'] = public_data.data['group_id']
        group_data['type'] = 'group'
        group_data['types'] = public_data.data['types']
        group_data['name'] = public_data.data['name']
        data_to_update_id = {'id': group_data['id']}
        update = {"$set": group_data}
        shared.db.entities.update_one(data_to_update_id, update, upsert=True)
        
    data_to_update_id = {'id': data_to_update['id']}
    update = {"$set": data_to_update}
    return shared.db.entities.find_one_and_update(data_to_update_id, update, upsert=True, return_document=ReturnDocument.AFTER)