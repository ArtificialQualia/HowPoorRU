from pymongo import errors

from jobs import shared
from jobs.shared import logger

from datetime import datetime
from datetime import timedelta
from datetime import timezone

datetime_format = "%Y-%m-%dT%X"

def process_character_wallets():
    logger.debug('start character wallet refresh')
    shared.initialize_job()

    user_cursor = shared.db.users.find({})
    
    for user_doc in user_cursor:
        process_character(user_doc)
    
    logger.debug('done character wallet refresh')
    
def process_corp_wallets():
    logger.debug('start corp wallet refresh')
    shared.initialize_job()

    user_cursor = shared.db.users.find({})
    
    for user_doc in user_cursor:
        process_corp(user_doc)
    
    logger.debug('done corp wallet refresh')
    
def process_corp(user_doc):
    if 'tokens' not in user_doc or 'corporation_id' not in user_doc:
        return
    if ('Scopes' not in user_doc or
            'esi-wallet.read_corporation_wallets.v1' not in user_doc['Scopes'].split(' ')):
        return
    
    character_data_to_update = {}
    refresh_token(user_doc, character_data_to_update)
    
    if len(character_data_to_update) > 0:
        character_filter = {'CharacterID': user_doc['CharacterID']}
        update = {"$set": character_data_to_update}
        shared.db.users.update_one(character_filter, update)
    
    corp_filter = {'corporation_id': user_doc['corporation_id']}
    corp_doc = shared.db.corporations.find_one(corp_filter)
    
    corp_data_to_update = {}
    op = shared.esiapp.op['get_corporations_corporation_id_wallets'](
        corporation_id=corp_doc['corporation_id']
    )
    wallet = shared.esiclient.request(op)
    if wallet.status != 200:
        logger.error(wallet.data)
        return
    corp_data_to_update['wallets'] = wallet.data
    
    last_update = datetime.fromtimestamp(corp_doc.get('last_journal_update') or 0.0, timezone.utc)
    now_utc = datetime.utcnow().replace(tzinfo=timezone.utc)
    if last_update + timedelta(hours=1) < now_utc:
        for wallet_division in range(1, 8):
            journal_division_entries = process_corp_journal(1, corp_doc, wallet_division)
            if len(journal_division_entries) > 0:
                corp_data_to_update['last_corp_journal_entry_' + str(wallet_division)] = journal_division_entries[0]['id']
                try:
                    shared.db.journals.insert_many(journal_division_entries, ordered=False)
                except errors.BulkWriteError as e:
                    logger.error(e)
        corp_data_to_update['last_journal_update'] = now_utc.timestamp()
        
    corp_filter = {'corporation_id': corp_doc['corporation_id']}
    update = {"$set": corp_data_to_update}
    shared.db.corporations.update_one(corp_filter, update)
    
def process_character(user_doc):
    if 'tokens' not in user_doc:
        return
    if ('Scopes' not in user_doc or
            'esi-wallet.read_character_wallet.v1' not in user_doc['Scopes'].split(' ')):
        return
    data_to_update = {}
    refresh_token(user_doc, data_to_update)
    op = shared.esiapp.op['get_characters_character_id_wallet'](
        character_id=user_doc['CharacterID']
    )
    wallet = shared.esiclient.request(op)
    if wallet.status != 200:
        logger.error(wallet.data)
        return
    data_to_update['wallet'] = wallet.data
    last_update = datetime.fromtimestamp(user_doc.get('last_journal_update') or 0.0, timezone.utc)
    now_utc = datetime.utcnow().replace(tzinfo=timezone.utc)
    if last_update + timedelta(hours=1) < now_utc:
        new_journal_entries = process_journal(1, user_doc)
        data_to_update['last_journal_update'] = now_utc.timestamp()
        if len(new_journal_entries) > 0:
            data_to_update['last_journal_entry'] = new_journal_entries[0]['id']
            try:
                shared.db.journals.insert_many(new_journal_entries, ordered=False)
            except errors.BulkWriteError as e:
                logger.error(e)
        
    character_filter = {'CharacterID': user_doc['CharacterID']}
    update = {"$set": data_to_update}
    shared.db.users.update_one(character_filter, update)
        
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
        tokens = shared.esisecurity.refresh()
        data_to_update['tokens'] = tokens
        delta_expire = timedelta(seconds=data_to_update['tokens']['expires_in'])
        token_expire = datetime.utcnow() + delta_expire
        data_to_update['tokens']['ExpiresOn'] = token_expire.strftime(datetime_format)

def process_journal(page, user_doc):
    last_journal_entry = user_doc.get('last_journal_entry') or 0
    op = shared.esiapp.op['get_characters_character_id_wallet_journal'](
        character_id=user_doc['CharacterID'],
        page=page
    )
    journal = shared.esiclient.request(op)
    num_pages = int(journal.header['X-Pages'][0])
    new_journal_entries = []
    for journal_entry in journal.data:
        if journal_entry['id'] > last_journal_entry:
            journal_entry['entity_id'] = user_doc['CharacterID']
            duplicate_found = look_for_duplicate(journal_entry)
            if duplicate_found:
                continue
            decode_journal_entry(journal_entry)
            new_journal_entries.append(journal_entry)
        else:
            return new_journal_entries
    if page < num_pages:
        next_pages_entries = process_journal(page+1, user_doc)
        return new_journal_entries.extend(next_pages_entries)
    return new_journal_entries

def process_corp_journal(page, corp_doc, division):
    last_journal_entry = corp_doc.get('last_corp_journal_entry_' + str(division)) or 0
    op = shared.esiapp.op['get_corporations_corporation_id_wallets_division_journal'](
        corporation_id=corp_doc['corporation_id'],
        division=division,
        page=page
    )
    journal = shared.esiclient.request(op)
    num_pages = int(journal.header['X-Pages'][0])
    new_journal_entries = []
    for journal_entry in journal.data:
        if journal_entry['id'] > last_journal_entry:
            journal_entry['entity_id'] = corp_doc['corporation_id']
            journal_entry['entity_wallet_division'] = division
            duplicate_found = look_for_duplicate(journal_entry, division)
            if duplicate_found:
                continue
            decode_journal_entry(journal_entry)
            new_journal_entries.append(journal_entry)
        else:
            return new_journal_entries
    if page < num_pages:
        next_pages_entries = process_corp_journal(page+1, corp_doc, division)
        return new_journal_entries.extend(next_pages_entries)
    return new_journal_entries
    
def look_for_duplicate(journal_entry, division=None):
    journal_filter = {'id': journal_entry['id']}
    result = shared.db.journals.find_one(journal_filter)
    if result is not None and result['entity_id'] != journal_entry['entity_id']:
        update = { '$set': {
                'balance_2': journal_entry['balance'],
                'entity_id_2': journal_entry['entity_id']
            }
        }
        if division:
            update['$set']['entity_wallet_division_2'] = division
        shared.db.journals.update_one(journal_filter, update)
        return True
    return False
    
def decode_journal_entry(journal_entry):
    journal_entry['date'] = journal_entry['date'].v.replace(tzinfo=timezone.utc).strftime("%Y-%m-%d %X")
    shared.decode_party_id(journal_entry['first_party_id'])
    shared.decode_party_id(journal_entry['second_party_id'])
    if 'tax_receiver_id' in journal_entry:
        shared.decode_party_id(journal_entry['tax_receiver_id'])
    