from jobs import shared
from jobs.shared import logger
from app.flask_shared_modules import rq

from requests import exceptions

from datetime import datetime
from datetime import timedelta
from datetime import timezone

datetime_format = "%Y-%m-%dT%X"

class JournalError(Exception):
    pass

@rq.job
def process_character_wallets():
    try:
        logger.debug('start character wallet refresh')

        user_cursor = shared.db.entities.find({ 'tokens': { '$exists': True } })
        
        for user_doc in user_cursor:
            try:
                process_character(user_doc)
            except JournalError:
                logger.error('Aborting character wallet processing for: ' + str(user_doc['id']))
            
        logger.debug('done character wallet refresh')
    except Exception as e:
        logger.exception(e)
        return
    
    
@rq.job
def process_corp_wallets():
    try:
        logger.debug('start corp wallet refresh')

        user_cursor = shared.db.entities.find({ '$and': [
                                            {'tokens': { '$exists': True } },
                                            {'corporation_id': { '$exists': True } }
                                            ] })
        for user_doc in user_cursor:
            try:
                process_corp(user_doc)
            except JournalError:
                logger.error('Aborting corp wallet processing for: ' + str(user_doc['id']))
    
        logger.debug('done corp wallet refresh')
    except Exception as e:
        logger.exception(e)
        return
    
def process_corp(user_doc):
    if ('scopes' not in user_doc or
            'esi-wallet.read_corporation_wallets.v1' not in user_doc['scopes'].split(' ')):
        return
    
    character_data_to_update = {}
    if not refresh_token(user_doc, character_data_to_update):
        return
    
    if len(character_data_to_update) > 0:
        character_filter = {'id': user_doc['id']}
        update = {"$set": character_data_to_update}
        shared.db.entities.update_one(character_filter, update)
    
    corp_filter = {'id': user_doc['corporation_id']}
    corp_doc = shared.db.entities.find_one(corp_filter)
    
    corp_data_to_update = {}
    op = shared.esiapp.op['get_corporations_corporation_id_wallets'](
        corporation_id=corp_doc['id']
    )
    wallet = shared.esiclient.request(op)
    if wallet.status != 200:
        logger.error('status: ' + str(wallet.status) + ' error with getting corp wallet data: ' + str(wallet.data))
        logger.error('headers: ' + str(wallet.header))
        logger.error('error with getting corp wallet data: ' + str(corp_doc['id']))
        if 'error' in wallet.data and wallet.data['error'] == 'Character does not have required role(s)':
            logger.error('Character ' + user_doc['name'] + 
                         ' does not seem to have roles to access corp wallet, removing read_corporation_wallets scope')
            data_to_update = {}
            data_to_update['scopes'] = user_doc['scopes'].replace('esi-wallet.read_corporation_wallets.v1', '')
            data_to_update['scopes'] = data_to_update['scopes'].replace('  ', '').strip()
            character_filter = {'id': user_doc['id']}
            update = {"$set": data_to_update}
            shared.db.entities.update_one(character_filter, update)
        return
    corp_data_to_update['wallets'] = wallet.data
    
    last_update = datetime.fromtimestamp(corp_doc.get('last_journal_update') or 0.0, timezone.utc)
    now_utc = datetime.utcnow().replace(tzinfo=timezone.utc)
    if last_update + timedelta(hours=1) < now_utc:
        for wallet_division in range(1, 8):
            missed_journal_string = 'missed_market_transactions_' + str(wallet_division)
            missed_journal_ids = corp_doc.get(missed_journal_string) or []
            process_missed_market_transactions(missed_journal_ids, corp_doc, wallet_division)
            journal_division_entries = process_journal(1, corp_doc, wallet_division)
            corp_data_to_update[missed_journal_string] = corp_doc[missed_journal_string]
            if len(journal_division_entries) > 0:
                corp_data_to_update['last_journal_entry_' + str(wallet_division)] = journal_division_entries[0]['id']
                for entry in journal_division_entries:
                    id_filter = {'id': entry['id']}
                    update = {'$set': entry}
                    shared.db.journals.update_one(id_filter, update, upsert=True)
        corp_data_to_update['last_journal_update'] = now_utc.timestamp()
        
    corp_filter = {'id': corp_doc['id']}
    update = {"$set": corp_data_to_update}
    shared.db.entities.update_one(corp_filter, update)
    
def process_character(user_doc):
    if ('scopes' not in user_doc or
            'esi-wallet.read_character_wallet.v1' not in user_doc['scopes'].split(' ')):
        return
    data_to_update = {}
    if not refresh_token(user_doc, data_to_update):
        return
    op = shared.esiapp.op['get_characters_character_id_wallet'](
        character_id=user_doc['id']
    )
    wallet = shared.esiclient.request(op)
    if wallet.status != 200:
        logger.error('status: ' + str(wallet.status) + ' error with getting character wallet data: ' + str(wallet.data))
        logger.error('headers: ' + str(wallet.header))
        logger.error('error with getting character wallet data: ' + str(user_doc['id']))
        return
    data_to_update['wallet'] = wallet.data
    last_update = datetime.fromtimestamp(user_doc.get('last_journal_update') or 0.0, timezone.utc)
    now_utc = datetime.utcnow().replace(tzinfo=timezone.utc)
    if last_update + timedelta(hours=1) < now_utc:
        missed_journal_ids = user_doc.get('missed_market_transactions') or []
        process_missed_market_transactions(missed_journal_ids, user_doc)
        new_journal_entries = process_journal(1, user_doc)
        data_to_update['missed_market_transactions'] = user_doc['missed_market_transactions']
        data_to_update['last_journal_update'] = now_utc.timestamp()
        if len(new_journal_entries) > 0:
            data_to_update['last_journal_entry'] = new_journal_entries[0]['id']
            for entry in new_journal_entries:
                id_filter = {'id': entry['id']}
                update = {'$set': entry}
                shared.db.journals.update_one(id_filter, update, upsert=True)
        
    character_filter = {'id': user_doc['id']}
    update = {"$set": data_to_update}
    shared.db.entities.update_one(character_filter, update)
        
def process_missed_market_transactions(missed_journal_ids, entity_doc, division=None):
    if division:
        entity_doc['missed_market_transactions_' + str(division)] = []
    else:
        entity_doc['missed_market_transactions'] = []
    
    for missed_journal_id in missed_journal_ids:
        id_filter = {'id': missed_journal_id}
        result = shared.db.journals.find_one(id_filter)
        if result is None:
            logger.error('journal entry in missed market transactions array not found, this should never happen')
            logger.error('entity with error: ' + str(entity_doc['id']) + ' journal entry error: ' + str(missed_journal_id))
            continue
        if 'context_id' in result and result['context_id_type'] == 'market_transaction_id':
            update_market_transaction(result, entity_doc, division)
            id_filter = {'id': result['id']}
            update = {'$set': result}
            shared.db.journals.update_one(id_filter, update)
        else:
            logger.error('journal entry in missed market transactions array has wrong context_id/type, this should never happen.')
            logger.error('entity with error: ' + str(entity_doc['id']) + ' journal entry error: ' + str(missed_journal_id))
        
        
def refresh_token(user_doc, data_to_update={}):
    access_token_expires = datetime.strptime(user_doc['tokens']['ExpiresOn'], datetime_format)
    sso_data = {
        'access_token': user_doc['tokens']['access_token'],
        'refresh_token': user_doc['tokens']['refresh_token'],
        'expires_in': (
            access_token_expires - datetime.utcnow()
        ).total_seconds()
    }
    shared.esisecurity.update_token(sso_data)
    if sso_data['expires_in'] <= 30:
        try:
            tokens = shared.esisecurity.refresh()
        except exceptions.SSLError:
            logger.error('ssl error refreshing token for ' + str(user_doc['id']))
            return False
        data_to_update['tokens'] = tokens
        delta_expire = timedelta(seconds=data_to_update['tokens']['expires_in'])
        token_expire = datetime.utcnow() + delta_expire
        data_to_update['tokens']['ExpiresOn'] = token_expire.strftime(datetime_format)
    return True

def process_journal(page, entity_doc, division=None):
    if division:
        last_journal_entry = entity_doc.get('last_journal_entry_' + str(division)) or 0
        op = shared.esiapp.op['get_corporations_corporation_id_wallets_division_journal'](
            corporation_id=entity_doc['id'],
            division=division,
            page=page
        )
    else:
        last_journal_entry = entity_doc.get('last_journal_entry') or 0
        op = shared.esiapp.op['get_characters_character_id_wallet_journal'](
            character_id=entity_doc['id'],
            page=page
        )
    journal = shared.esiclient.request(op)
    if journal.status != 200:
        logger.error('status: ' + str(journal.status) + ' error with getting journal data: ' + str(journal.data))
        logger.error('headers: ' + str(journal.header))
        logger.error('error with getting journal data: ' + str(entity_doc['id']))
        raise JournalError()
    num_pages = int(journal.header['X-Pages'][0])
    new_journal_entries = []
    for journal_entry in journal.data:
        if journal_entry['id'] > last_journal_entry:
            if journal_entry['first_party_id'] == entity_doc['id']:
                journal_entry['first_party_balance'] = journal_entry.pop('balance')
                journal_entry['first_party_amount'] = journal_entry.pop('amount')
                journal_entry['second_party_amount'] = journal_entry['first_party_amount'] * -1
                if division:
                    journal_entry['first_party_wallet_division'] = division
            elif journal_entry['second_party_id'] == entity_doc['id']:
                journal_entry['second_party_balance'] = journal_entry.pop('balance')
                journal_entry['second_party_amount'] = journal_entry.pop('amount')
                journal_entry['first_party_amount'] = journal_entry['second_party_amount'] * -1
                if division:
                    journal_entry['second_party_wallet_division'] = division
            elif 'tax_receiver_id' in journal_entry and journal_entry['tax_receiver_id'] == entity_doc['id']:
                journal_entry['tax_receiver_balance'] = journal_entry.pop('balance')
                del journal_entry['amount']
                if division:
                    journal_entry['tax_receiver_wallet_division'] = division
            else:
                logger.info('Dont know what to do with: ' + str(journal_entry))
                logger.info('This may be a corp transaction that doesnt have the corp listed')
                logger.info('Entity with error: ' + str(entity_doc['id']))
                journal_entry['corp_amount'] = journal_entry.pop('amount')
                journal_entry['second_party_amount'] = abs(journal_entry['corp_amount'])
                journal_entry['first_party_amount'] = journal_entry['second_party_amount'] * -1
                journal_entry['corp_id'] = entity_doc['id']
                journal_entry['corp_balance'] = journal_entry.pop('balance')
                if division:
                    journal_entry['corp_wallet_division'] = division
                else:
                    logger.error(str(journal_entry) + ' is not a corp transaction!  This is bad data!')
            decode_journal_entry(journal_entry, entity_doc, division)
            new_journal_entries.append(journal_entry)
        else:
            return new_journal_entries
    if page < num_pages:
        next_pages_entries = process_journal(page+1, entity_doc, division)
        if next_pages_entries:
            return new_journal_entries.extend(next_pages_entries)
    return new_journal_entries
    
def decode_journal_entry(journal_entry, entity_doc, division):
    journal_entry['date'] = journal_entry['date'].v.replace(tzinfo=timezone.utc).timestamp()
    
    shared.decode_party_id(journal_entry['first_party_id'])
    shared.decode_party_id(journal_entry['second_party_id'])
    if 'tax_receiver_id' in journal_entry:
        shared.decode_party_id(journal_entry['tax_receiver_id'])
            
    if 'context_id' in journal_entry:
        decode_context_id(journal_entry, entity_doc, division)
    
def decode_context_id(journal_entry, entity_doc, division):
    id_filter = {'id': journal_entry['context_id']}
    result = shared.db.entities.find_one(id_filter)
    if result is not None:
        return
    
    if journal_entry['context_id_type'] == 'character_id':
        shared.user_update(journal_entry['context_id'])
    elif journal_entry['context_id_type'] == 'corporation_id':
        shared.corp_update(journal_entry['context_id'])
    elif journal_entry['context_id_type'] == 'system_id':
        update_system(journal_entry['context_id'])
    elif journal_entry['context_id_type'] == 'eve_system' or journal_entry['context_id_type'] == 'type_id':
        update_item(journal_entry['context_id'], 'ship')
    elif journal_entry['context_id_type'] == 'market_transaction_id':
        update_market_transaction(journal_entry, entity_doc, division)
    elif journal_entry['context_id_type'] == 'station_id':
        update_station(journal_entry['context_id'])
    else:
        return
    
def update_market_transaction(journal_entry, entity_doc, division):
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
                journal_entry['transaction_context_id'] = journal_entry['context_id']
                journal_entry['transaction_context_type'] = journal_entry['context_id_type']
                journal_entry['unit_price'] = transaction['unit_price']
                journal_entry['quantity'] = transaction['quantity']
                journal_entry['context_id_type'] = 'location_id type_id'
                journal_entry['context_id'] = [transaction['location_id'], transaction['type_id']]
                id_filter = {'id': transaction['type_id']}
                result = shared.db.entities.find_one(id_filter)
                if result is None:
                    update_item(transaction['type_id'], 'item')
                id_filter = {'id': transaction['location_id']}
                result = shared.db.entities.find_one(id_filter)
                if result is None:
                    update_station(transaction['location_id'])
                if journal_entry['ref_type'] == 'market_escrow' and journal_entry['first_party_id'] == journal_entry['second_party_id']:
                    journal_entry['second_party_id'] = transaction['client_id']
                    shared.decode_party_id(journal_entry['second_party_id'])
                return
            elif transaction['transaction_id'] < journal_entry['context_id']:
                break
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
    shared.db.entities.update_one(data_to_update_id, update, upsert=True)
    

def update_system(system_id):
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
    shared.db.entities.update_one(data_to_update_id, update, upsert=True)

def update_constellation(constellation_id):
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
    shared.db.entities.update_one(data_to_update_id, update, upsert=True)