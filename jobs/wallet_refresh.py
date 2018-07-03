"""
 contains jobs to update both character and corp wallets and journals
"""

from jobs import shared
from jobs.shared import logger
from jobs import context_handler
from app.flask_shared_modules import rq

from requests import exceptions
from esipy.exceptions import APIException

from datetime import datetime
from datetime import timedelta
from datetime import timezone

datetime_format = "%Y-%m-%dT%X"

# custom exception so that journal processing can be aborted on specific errors
class JournalError(Exception):
    pass

@rq.job
def process_character_wallets():
    """ processes character wallets for all characters that have tokens """
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
    """ processes corp wallets for all characters that have tokens """
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
    """ if the esi token has the correct scope, update the wallet amount and see if it is time for a journal update """
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
            process_journal(1, corp_doc, wallet_division)
        corp_data_to_update['last_journal_update'] = now_utc.timestamp()
        
    corp_filter = {'id': corp_doc['id']}
    update = {"$set": corp_data_to_update}
    shared.db.entities.update_one(corp_filter, update)
    
def process_character(user_doc):
    """ if the esi token has the correct scope, update the wallet amount and see if it is time for a journal update """
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
        process_journal(1, user_doc)
        data_to_update['last_journal_update'] = now_utc.timestamp()
        
    character_filter = {'id': user_doc['id']}
    update = {"$set": data_to_update}
    shared.db.entities.update_one(character_filter, update)
        
def process_missed_market_transactions(missed_journal_ids, entity_doc, division=None):
    """ 
    if there are journal entries that are still missing extra context data
    that comes from 'transactions' endpoint, attempt to update those entries
    """
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
        if 'context' in result and 'type' in result['context'][0] and result['context'][0]['type'] == 'market_transaction_id':
            result['context_id_type'] = result['context'][0]['type']
            result['context_id'] = result['context'][0]['id']
            result['context'] = [{}]
            context_handler.update_market_transaction(result, entity_doc, division)
            del result['context_id_type']
            del result['context_id']
            id_filter = {'id': result['id']}
            update = {'$set': result}
            shared.db.journals.update_one(id_filter, update)
        else:
            logger.error('journal entry in missed market transactions array has wrong context_id/type, this should never happen.')
            logger.error('entity with error: ' + str(entity_doc['id']) + ' journal entry error: ' + str(missed_journal_id))
        
        
def refresh_token(user_doc, data_to_update={}):
    """ update the ESI token if necessary returns False if the update fails """
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
        except APIException as e:
            logger.error('error refreshing token for: ' + str(user_doc['id']))
            logger.error('error is: ' + str(e))
            return False
        data_to_update['tokens'] = tokens
        delta_expire = timedelta(seconds=data_to_update['tokens']['expires_in'])
        token_expire = datetime.utcnow() + delta_expire
        data_to_update['tokens']['ExpiresOn'] = token_expire.strftime(datetime_format)
    return True

def process_journal(page, entity_doc, division=None):
    """ handles updating the journal entries for both characters and corps, also handles pagination for journals """
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
    if page < num_pages and journal.data[-1]['id'] > last_journal_entry:
        process_journal(page+1, entity_doc, division)
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
                logger.info('Journal entry doesnt match any provided entity fields: ' + str(journal_entry))
                logger.info('This may be a corp transaction that doesnt have the corp listed')
                logger.info('Entity with error: ' + str(entity_doc['id']))
                if journal_entry['amount'] < 0:
                    journal_entry['second_party_amount'] = abs(journal_entry.pop('amount'))
                    journal_entry['first_party_amount'] = journal_entry['second_party_amount'] * -1
                    journal_entry['first_party_corp_balance'] = journal_entry.pop('balance')
                    journal_entry['first_party_corp_id'] = entity_doc['id']
                    journal_entry['first_party_corp_name'] = entity_doc['name']
                    if division:
                        journal_entry['first_party_corp_wallet_division'] = division
                    else:
                        logger.error(str(journal_entry['id']) + ' is not a corp transaction!  This is bad data!')
                elif journal_entry['amount'] > 0:
                    journal_entry['second_party_amount'] = abs(journal_entry.pop('amount'))
                    journal_entry['first_party_amount'] = journal_entry['second_party_amount'] * -1
                    journal_entry['second_party_corp_balance'] = journal_entry.pop('balance')
                    journal_entry['second_party_corp_id'] = entity_doc['id']
                    journal_entry['second_party_corp_name'] = entity_doc['name']
                    if division:
                        journal_entry['second_party_corp_wallet_division'] = division
                    else:
                        logger.error(str(journal_entry['id']) + ' is not a corp transaction!  This is bad data!')
                else:
                    logger.error('Corp amount is 0!  Cant assign the corp to a party, this will lead to bad data.')
            decode_journal_entry(journal_entry, entity_doc, division)
            new_journal_entries.append(journal_entry)
        else:
            break
    if len(new_journal_entries) > 0:
        if division:
            entity_doc['last_journal_entry' + str(division)] = new_journal_entries[0]['id']
        else:
            entity_doc['last_journal_entry'] = new_journal_entries[0]['id']
        for entry in new_journal_entries:
            id_filter = {'id': entry['id']}
            update = {'$set': entry}
            shared.db.journals.update_one(id_filter, update, upsert=True) 
        entity_filter = {'id': entity_doc['id']}
        update = {"$set": entity_doc}
        shared.db.entities.update_one(entity_filter, update)
    
def decode_journal_entry(journal_entry, entity_doc, division):
    """ add embedded docs for journal entry fields """
    journal_entry['date'] = journal_entry['date'].v.replace(tzinfo=timezone.utc).timestamp()
    
    result = shared.decode_party_id(journal_entry['first_party_id'])
    if result:
        journal_entry['first_party_name'] = result['name']
        journal_entry['first_party_type'] = result['type']
        
    result = shared.decode_party_id(journal_entry['second_party_id'])
    if result:
        journal_entry['second_party_name'] = result['name']
        journal_entry['second_party_type'] = result['type']
        
    if 'tax_receiver_id' in journal_entry:
        result = shared.decode_party_id(journal_entry['tax_receiver_id'])
        if result:
            journal_entry['tax_receiver_name'] = result['name']
            
    if 'context_id' in journal_entry:
        context_handler.decode_context_id(journal_entry, entity_doc, division)
    