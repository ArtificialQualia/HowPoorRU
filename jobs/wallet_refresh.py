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

    user_cursor = shared.db.entities.find({ 'tokens': { '$exists': True } })
    
    for user_doc in user_cursor:
        process_character(user_doc)
    
    logger.debug('done character wallet refresh')
    
def process_corp_wallets():
    logger.debug('start corp wallet refresh')
    shared.initialize_job()

    user_cursor = shared.db.entities.find({ '$and': [
                                        {'tokens': { '$exists': True } },
                                        {'corporation_id': { '$exists': True } }
                                        ] })
    for user_doc in user_cursor:
        process_corp(user_doc)
    
    logger.debug('done corp wallet refresh')
    
def process_corp(user_doc):
    if ('scopes' not in user_doc or
            'esi-wallet.read_corporation_wallets.v1' not in user_doc['scopes'].split(' ')):
        return
    
    character_data_to_update = {}
    refresh_token(user_doc, character_data_to_update)
    
    if len(character_data_to_update) > 0:
        character_filter = {'id': user_doc['id']}
        update = {"$set": character_data_to_update}
        shared.db.entities.update_one(character_filter, update)
    
    corp_filter = {'id': user_doc['id']}
    corp_doc = shared.db.entities.find_one(corp_filter)
    
    corp_data_to_update = {}
    op = shared.esiapp.op['get_corporations_corporation_id_wallets'](
        corporation_id=corp_doc['id']
    )
    wallet = shared.esiclient.request(op)
    if wallet.status != 200:
        logger.error(wallet.data)
        if 'error' in wallet.data and wallet.data['error'] == 'Character is not in the corporation':
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
            journal_division_entries = process_journal(1, corp_doc, wallet_division)
            if len(journal_division_entries) > 0:
                corp_data_to_update['last_journal_entry_' + str(wallet_division)] = journal_division_entries[0]['id']
                try:
                    shared.db.journals.insert_many(journal_division_entries, ordered=False)
                except errors.BulkWriteError as e:
                    logger.error(e)
        corp_data_to_update['last_journal_update'] = now_utc.timestamp()
        
    corp_filter = {'id': corp_doc['id']}
    update = {"$set": corp_data_to_update}
    shared.db.entities.update_one(corp_filter, update)
    
def process_character(user_doc):
    if ('scopes' not in user_doc or
            'esi-wallet.read_character_wallet.v1' not in user_doc['scopes'].split(' ')):
        return
    data_to_update = {}
    refresh_token(user_doc, data_to_update)
    op = shared.esiapp.op['get_characters_character_id_wallet'](
        character_id=user_doc['id']
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
        
    character_filter = {'id': user_doc['id']}
    update = {"$set": data_to_update}
    shared.db.entities.update_one(character_filter, update)
        
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
            else:
                logger.error('Dont know what to do with: ' + str(journal_entry))
                logger.error('Entity with error: ' + entity_doc['id'])
            decode_journal_entry(journal_entry)
            new_journal_entries.append(journal_entry)
        else:
            return new_journal_entries
    if page < num_pages:
        next_pages_entries = process_journal(page+1, entity_doc, division)
        return new_journal_entries.extend(next_pages_entries)
    return new_journal_entries
    
def decode_journal_entry(journal_entry):
    journal_entry['date'] = journal_entry['date'].v.replace(tzinfo=timezone.utc).strftime("%Y-%m-%d %X")
    shared.decode_party_id(journal_entry['first_party_id'])
    shared.decode_party_id(journal_entry['second_party_id'])
    if 'tax_receiver_id' in journal_entry:
        shared.decode_party_id(journal_entry['tax_receiver_id'])
    