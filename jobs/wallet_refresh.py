from jobs import shared

from datetime import datetime
from datetime import timedelta
from datetime import timezone

def process_wallets():
    print(datetime.now())
    print('start wallet refresh')
    shared.initialize_job()

    user_cursor = shared.db.users.find({})
    
    datetime_format = "%Y-%m-%dT%X"
    for user_doc in user_cursor:
        if 'tokens' not in user_doc:
            continue
        if 'Scopes' not in user_doc or user_doc['Scopes'] != 'esi-wallet.read_character_wallet.v1':
            continue
        data_to_update = {}
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
        op = shared.esiapp.op['get_characters_character_id_wallet'](
            character_id=user_doc['CharacterID']
        )
        wallet = shared.esiclient.request(op)
        if wallet.status != 200:
            print(wallet.data)
            continue
        data_to_update['wallet'] = wallet.data
        last_update = datetime.fromtimestamp(user_doc.get('last_journal_update') or 0.0, timezone.utc)
        now_utc = datetime.utcnow().replace(tzinfo=timezone.utc)
        if last_update + timedelta(hours=1) < now_utc:
            new_journal_entries = process_journal(1, user_doc)
            data_to_update['last_journal_update'] = now_utc.timestamp()
            if len(new_journal_entries) > 0:
                data_to_update['last_journal_entry'] = new_journal_entries[0]['id']
                shared.db.journals.insert_many(new_journal_entries)
            
        character_filter = {'CharacterID': user_doc['CharacterID']}
        update = {"$set": data_to_update}
        shared.db.users.update_one(character_filter, update)
    print(datetime.now())
    print('done wallet refresh')
        
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
    
def look_for_duplicate(journal_entry):
    journal_filter = {'id': journal_entry['id']}
    result = shared.db.journals.find_one(journal_filter)
    if result is not None:
        update = { '$set': {
                'balance_2': journal_entry['balance'],
                'entity_id_2': journal_entry['entity_id']
            }
        }
        shared.db.journals.update_one(journal_filter, update)
        return True
    return False
    
def decode_journal_entry(journal_entry):
    journal_entry['date'] = journal_entry['date'].v.replace(tzinfo=timezone.utc).strftime("%Y-%m-%d %X")
    shared.decode_party_id(journal_entry['first_party_id'])
    shared.decode_party_id(journal_entry['second_party_id'])
    if 'tax_receiver_id' in journal_entry:
        shared.decode_party_id(journal_entry['tax_receiver_id'])
    