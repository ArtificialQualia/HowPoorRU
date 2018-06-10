import pymongo
import bson

from flask import render_template
from flask import url_for
from flask import abort
from flask import request
from flask import jsonify
from flask import Blueprint

from flask_login import current_user
from flask_login import login_required

import config
from app.flask_shared_modules import mongo
from app.flask_shared_modules import r

import re
from collections import OrderedDict
from datetime import datetime
from datetime import timezone

main_pages = Blueprint('main_pages', __name__)

@main_pages.route('/')
@main_pages.route('/<int:page_number>')
def index(page_number=1, *args):
    """ paginated main index page, contains latest journal entries """
    # ensure page is in valid range
    page_range_check(page_number)
    
    # find all transactions in database
    journal_cursor = mongo.db.journals.find({})
    
    # calculate number of entries to skip in database
    skip_amount = (page_number - 1) * config.PAGE_SIZE
    
    # sort (required for ordered transactions), skip over entries based on our page number,
    # then limit the number of results returned
    journal_cursor.sort('id', -1).skip(skip_amount).limit(config.PAGE_SIZE)
    
    # initialize empty journal_entries to ensure something gets passed to render_template
    journal_entries = []
    for entry in journal_cursor:
        # if this corp wasn't the receiver of tax, then it had to pay out the tax
        if 'tax' in entry:
            entry['tax'] = entry['tax'] * -1
            
        # turn common line items in journal entry into proper names and generated URLs
        process_common_fields(entry)
        
        # sort the journal entry by name so line items are less random in transaction details modal
        sorted_entry = OrderedDict(sorted(entry.items(), key=lambda x: x[0]))
        
        journal_entries.append(sorted_entry)
        
    top_character_bytes = r.hgetall('top_character_wallet')
    top_character = redis_bytes_to_data(top_character_bytes)
    top_character['url'] = url_for('.character', entity_id=top_character.get('id') or 0)
        
    top_corp_bytes = r.hgetall('top_corp_wallet')
    top_corp = redis_bytes_to_data(top_corp_bytes)
    top_corp['url'] = url_for('.corporation', entity_id=top_corp.get('id') or 0)
        
    top_tx_bytes = r.hgetall('top_tx_day')
    top_tx = redis_bytes_to_data(top_tx_bytes)
    top_tx = mongo.db.journals.find_one({'id': top_tx.get('id') or 0})
    if top_tx:
        process_common_fields(top_tx)
        top_tx = OrderedDict(sorted(top_tx.items(), key=lambda x: x[0]))
    else:
        top_tx = {}
    
    return render_template('index.html', journal_entries=journal_entries, page_number=page_number,
                           top_character=top_character, top_corp=top_corp, top_tx=top_tx)

@main_pages.route('/character/<int:entity_id>')
@main_pages.route('/character/<int:entity_id>/<int:page_number>')
@main_pages.route('/character/<int:entity_id>/<tx_type>')
@main_pages.route('/character/<int:entity_id>/<tx_type>/<int:page_number>')
def character(entity_id, page_number=1, tx_type='all'):
    """ paginated character page, has character details and journal entries """
    # ensure page is in valid range
    page_range_check(page_number)
    
    request.view_args['tx_type'] = tx_type
    
    # find user in database, or return a 404
    character_filter = {'id': entity_id}
    character_data = mongo.db.entities.find_one_or_404(character_filter)
    if character_data['type'] != 'character':
        abort(404)
    
    # we turn special database fields into proper names and urls
    conditional_decode(character_data, 'corporation_')
    conditional_decode(character_data, 'alliance_')
    
    # find all journal entries that this entity is involved in
    journal_search = make_entity_filter(entity_id, tx_type)
    journal_cursor = mongo.db.journals.find(journal_search)
    
    # calculate number of entries to skip in database
    skip_amount = (page_number - 1) * config.PAGE_SIZE
    
    # sort (required for ordered transactions), skip over entries based on our page number,
    # then limit the number of results returned
    journal_cursor.sort('id', -1).skip(skip_amount).limit(config.PAGE_SIZE)
    
    # initialize empty journal_entries to ensure something gets passed to render_template
    journal_entries = []
    for entry in journal_cursor:
        # since this is a character, it pays tax not gains it
        if 'tax_receiver_id' in entry:
            entry['tax'] = entry['tax'] * -1
            
        # turn common line items in journal entry into proper names and generated URLs
        process_common_fields(entry)
        
        # sort the journal entry by name so line items are less random in transaction details modal
        sorted_entry = OrderedDict(sorted(entry.items(), key=lambda x: x[0]))
        
        journal_entries.append(sorted_entry)
        
    return render_template('character.html', entity_data=character_data, journal_entries=journal_entries, page_number=page_number)

@main_pages.route('/corporation/<int:entity_id>')
@main_pages.route('/corporation/<int:entity_id>/<int:page_number>')
@main_pages.route('/corporation/<int:entity_id>/<tx_type>')
@main_pages.route('/corporation/<int:entity_id>/<tx_type>/<int:page_number>')
def corporation(entity_id, page_number=1, tx_type='all'):
    """ paginated corporation page, has corp details and journal entries """
    # ensure page is in valid range
    page_range_check(page_number)
    
    request.view_args['tx_type'] = tx_type
    
    # find user in database, or return a 404
    corp_filter = {'id': entity_id}
    corp_data = mongo.db.entities.find_one_or_404(corp_filter)
    if corp_data['type'] != 'corporation':
        abort(404)
    
    # we turn special database fields into proper names and urls
    conditional_decode(corp_data, 'ceo_')
    conditional_decode(corp_data, 'alliance_')
    
    if 'wallets' in corp_data:
        corp_data['wallets_total'] = 0
        for wallet in (corp_data['wallets'] or None):
            corp_data['wallets_total'] += wallet['balance']
    
    # find all journal entries that this entity is involved in
    journal_search = make_entity_filter(entity_id, tx_type)
    journal_cursor = mongo.db.journals.find(journal_search)
    
    # calculate number of entries to skip in database
    skip_amount = (page_number - 1) * config.PAGE_SIZE
    
    # sort (required for ordered transactions), skip over entries based on our page number,
    # then limit the number of results returned
    journal_cursor.sort('id', -1).skip(skip_amount).limit(config.PAGE_SIZE)
    
    # initialize empty journal_entries to ensure something gets passed to render_template
    journal_entries = []
    for entry in journal_cursor:
        # if this corp wasn't the receiver of tax, then it had to pay out the tax
        if 'tax' in entry and entry['tax_receiver_id'] != entity_id:
            entry['tax'] = entry['tax'] * -1
            
        # turn common line items in journal entry into proper names and generated URLs
        process_common_fields(entry)
        
        # sort the journal entry by name so line items are less random in transaction details modal
        sorted_entry = OrderedDict(sorted(entry.items(), key=lambda x: x[0]))
        
        journal_entries.append(sorted_entry)
        
    return render_template('corporation.html', entity_data=corp_data, journal_entries=journal_entries, page_number=page_number)

@main_pages.route('/alliance/<int:entity_id>')
@main_pages.route('/alliance/<int:entity_id>/<int:page_number>')
@main_pages.route('/alliance/<int:entity_id>/<tx_type>')
@main_pages.route('/alliance/<int:entity_id>/<tx_type>/<int:page_number>')
def alliance(entity_id, page_number=1, tx_type='all'):
    """ paginated alliance page, has alliance details and journal entries from all corps """
    # ensure page is in valid range
    page_range_check(page_number)
    
    request.view_args['tx_type'] = tx_type
    
    # find user in database, or return a 404
    alliance_filter = {'id': entity_id}
    alliance_data = mongo.db.entities.find_one_or_404(alliance_filter)
    if alliance_data['type'] != 'alliance':
        abort(404)
    
    # if we don't have any corps from ESI yet, then there is no data to show
    if 'corps' not in alliance_data:
        abort(404)
    
    # we turn special database fields into proper names and urls
    conditional_decode(alliance_data, 'executor_corporation_')
    
    # find all journal entries that this entity's corps are involved in
    journal_search = make_entity_filter({ '$in': alliance_data['corps'] }, tx_type)
    journal_cursor = mongo.db.journals.find(journal_search)
    
    # calculate number of entries to skip in database
    skip_amount = (page_number - 1) * config.PAGE_SIZE
    
    # sort (required for ordered transactions), skip over entries based on our page number,
    # then limit the number of results returned
    journal_cursor.sort('id', -1).skip(skip_amount).limit(config.PAGE_SIZE)
    
    # initialize empty journal_entries to ensure something gets passed to render_template
    journal_entries = []
    for entry in journal_cursor:
        if 'tax' in entry and entry['tax_receiver_id'] not in alliance_data['corps']:
            entry['tax'] = entry['tax'] * -1
            
        # turn common line items in journal entry into proper names and generated URLs
        process_common_fields(entry)
        
        # sort the journal entry by name so line items are less random in transaction details modal
        sorted_entry = OrderedDict(sorted(entry.items(), key=lambda x: x[0]))
        
        journal_entries.append(sorted_entry)
        
    return render_template('alliance.html', entity_data=alliance_data, journal_entries=journal_entries, page_number=page_number)

@main_pages.route('/system/<int:entity_id>')
@main_pages.route('/system/<int:entity_id>/<int:page_number>')
def system(entity_id, page_number=1):
    id_filter = {'id': entity_id}
    entity_data = mongo.db.entities.find_one_or_404(id_filter)
    if entity_data['type'] != 'system':
        abort(404)
    find_ids = [entity_id]
    if 'stations' in entity_data:
        find_ids.extend(entity_data['stations'])
    return context_id_routes({ '$in': find_ids }, 'system', page_number, entity_data)

@main_pages.route('/constellation/<int:entity_id>')
@main_pages.route('/constellation/<int:entity_id>/<int:page_number>')
def constellation(entity_id, page_number=1):
    id_filter = {'id': entity_id}
    entity_data = mongo.db.entities.find_one_or_404(id_filter)
    if entity_data['type'] != 'constellation':
        abort(404)
    find_ids = entity_data['systems']
    for system in entity_data['systems']:
        id_filter = {'id': system}
        system_data = mongo.db.entities.find_one(id_filter)
        if system_data:
            if 'stations' in system_data:
                find_ids.extend(system_data['stations'])
    return context_id_routes({ '$in': find_ids }, 'constellation', page_number, entity_data)

@main_pages.route('/region/<int:entity_id>')
@main_pages.route('/region/<int:entity_id>/<int:page_number>')
def region(entity_id, page_number=1):
    id_filter = {'id': entity_id}
    entity_data = mongo.db.entities.find_one_or_404(id_filter)
    if entity_data['type'] != 'region':
        abort(404)
    system_ids = []
    for constellation in entity_data['constellations']:
        id_filter = {'id': constellation}
        constellation_data = mongo.db.entities.find_one(id_filter)
        if constellation_data:
            system_ids.extend(constellation_data['systems'])
            for system in constellation_data['systems']:
                id_filter = {'id': system}
                system_data = mongo.db.entities.find_one(id_filter)
                if system_data:
                    if 'stations' in system_data:
                        system_ids.extend(system_data['stations'])
    return context_id_routes({ '$in': system_ids }, 'region', page_number, entity_data)

@main_pages.route('/ship/<int:entity_id>')
@main_pages.route('/ship/<int:entity_id>/<int:page_number>')
def ship(entity_id, page_number=1):
    return context_id_routes(entity_id, 'ship', page_number)

@main_pages.route('/item/<int:entity_id>')
@main_pages.route('/item/<int:entity_id>/<int:page_number>')
def item(entity_id, page_number=1):
    return context_id_routes(entity_id, 'item', page_number)

@main_pages.route('/station/<int:entity_id>')
@main_pages.route('/station/<int:entity_id>/<int:page_number>')
def station(entity_id, page_number=1):
    return context_id_routes(entity_id, 'station', page_number)

@main_pages.route('/group/<int:entity_id>')
@main_pages.route('/group/<int:entity_id>/<int:page_number>')
def group(entity_id, page_number=1):
    id_filter = {'id': entity_id}
    entity_data = mongo.db.entities.find_one_or_404(id_filter)
    if entity_data['type'] != 'group':
        abort(404)
    return context_id_routes({ '$in': entity_data['types'] }, 'group', page_number, entity_data)

@main_pages.route('/faq')
def faq():
    return render_template('faq.html')

def context_id_routes(entity_id, context_type, page_number, entity_group_data=None):
    # ensure page is in valid range
    page_range_check(page_number)
    
    # find user in database, or return a 404
    if not entity_group_data:
        id_filter = {'id': entity_id}
        entity_data = mongo.db.entities.find_one_or_404(id_filter)
        if entity_data['type'] != context_type:
            abort(404)
    else:
        entity_data = entity_group_data
    
    conditional_decode(entity_data, 'group_')
    conditional_decode(entity_data, 'system_')
    
    # find all journal entries that this entity's corps are involved in
    journal_search = {'context_id': entity_id}
    journal_cursor = mongo.db.journals.find(journal_search)
    
    # calculate number of entries to skip in database
    skip_amount = (page_number - 1) * config.PAGE_SIZE
    
    # sort (required for ordered transactions), skip over entries based on our page number,
    # then limit the number of results returned
    journal_cursor.sort('id', -1).skip(skip_amount).limit(config.PAGE_SIZE)
    
    # initialize empty journal_entries to ensure something gets passed to render_template
    journal_entries = []
    for entry in journal_cursor:
        # turn common line items in journal entry into proper names and generated URLs
        process_common_fields(entry)
        
        # sort the journal entry by name so line items are less random in transaction details modal
        sorted_entry = OrderedDict(sorted(entry.items(), key=lambda x: x[0]))
        
        journal_entries.append(sorted_entry)
        
    return render_template(str(context_type) + '.html', entity_data=entity_data, journal_entries=journal_entries, page_number=page_number)

@main_pages.route('/search', methods=['POST'])
def search():
    if 'search_string' not in request.form:
        abort(400)
    sanitized_string = '^(.*?)(' + re.escape(request.form['search_string']) + ')(.*)'
    python_regex = re.compile(sanitized_string, re.IGNORECASE)
    bson_regex = bson.regex.Regex.from_native(python_regex)
    regex_find = {'name': bson_regex}
    results = mongo.db.entities.find(regex_find)
    limited_results = []
    for result in results.limit(10):
        one_result = [result['id']]
        match = python_regex.match(result['name'])
        bolded_name = match.group(1) + "<strong>" + match.group(2) + "</strong>" + match.group(3)
        one_result.append(bolded_name)
        one_result.append(result['type'])
        one_result.append(url_for('.'+result['type'], entity_id=result['id']))
        if result['type'] == 'character':
            one_result.append('https://image.eveonline.com/Character/' + str(result['id']) + '_32.jpg')
        elif result['type'] == 'ship':
            one_result.append('https://image.eveonline.com/Render/' + str(result['id']) + '_32.png')
        elif result['type'] == 'item':
            one_result.append('https://image.eveonline.com/Type/' + str(result['id']) + '_32.png')
        elif result['type'] == 'station':
            one_result.append('https://image.eveonline.com/Render/' + str(result['type_id']) + '_32.png')
        elif result['type'] == 'system' or result['type'] == 'constellation' or result['type'] == 'region':
            one_result.append(url_for('static', filename='img/' + result['type'] + '.png'))
        else:
            one_result.append('https://image.eveonline.com/' + result['type'] + '/' + str(result['id']) + '_32.png')
        limited_results.append(one_result)
    return jsonify(limited_results)

@main_pages.route('/account')
@login_required
def account():
    character_filter = {'id': current_user.character_id}
    character_data = mongo.db.entities.find_one_or_404(character_filter)
    scopes_list = character_data['scopes'].split()
    
    remove_scope = request.args.get('remove_scope')
    if remove_scope is not None:
        data_to_update = {}
        for scope in scopes_list:
            if scope == remove_scope:
                scopes_list.remove(scope)
        data_to_update['scopes'] = " ".join(scopes_list)
        update = {"$set": data_to_update}
        character_data = mongo.db.entities.find_one_and_update(character_filter, update, return_document=pymongo.ReturnDocument.AFTER)
        scopes_list = character_data['scopes'].split()
    
    character_data['scopes'] = scopes_list
    return render_template('account.html', user=character_data)

def page_range_check(page_number):
    """ returns a 404 if the page is outside the supported number of pages """
    # TODO: change these to config values and ensure that value is passed to paginated.html
    if page_number > 10 or page_number < 1:
        abort(404)
        
def conditional_decode(entry, id_prefix):
    """ helper to decode entity database ids to names and urls """
    if (id_prefix + 'id') in entry:
        if entry[id_prefix + 'id'] == 1:
            entry[id_prefix + 'id'] = 'Character'
            return
        if entry[id_prefix + 'id'] == 2:
            entry[id_prefix + 'id'] = 'Corporation'
            return
        id_filter = {'id': entry[id_prefix + 'id']}
        result = mongo.db.entities.find_one(id_filter)
        if result is not None:
            entry[id_prefix + 'name'] = result['name']
            entry[id_prefix + 'url'] = url_for('.' + result['type'], entity_id=result['id'])
            
def context_decode(entry):
    if 'context_id' in entry:
        if isinstance(entry['context_id'], (list,)):
            entry['location_id'] = entry['context_id'][0]
            entry['type_id'] = entry['context_id'][1]
            conditional_decode(entry, 'location_')
            conditional_decode(entry, 'type_')
        else:
            conditional_decode(entry, 'context_')

def redis_bytes_to_data(redis_object):
    decoded_object = {}
    for key, value in redis_object.items():
        if key.decode('utf-8') == 'wallet' or key.decode('utf-8') == 'amount':
            decoded_object[key.decode('utf-8')] = float(value.decode('utf-8'))
        elif key.decode('utf-8').endswith('id'):
            decoded_object[key.decode('utf-8')] = int(value.decode('utf-8'))
        else:
            decoded_object[key.decode('utf-8')] = value.decode('utf-8')
    return decoded_object

def make_entity_filter(entity_filter, tx_type):
    journal_search = {}
    if tx_type == 'all':
        journal_search = {'$or':[ 
            {'first_party_id': entity_filter},
            {'second_party_id': entity_filter},
            {'corp_id': entity_filter},
            {'tax_receiver_id': entity_filter},
            {'context_id': entity_filter}
        ]}
    elif tx_type == 'gains':
        journal_search = {'$or':[ 
            {'$and': [{'first_party_id': entity_filter}, {'first_party_amount': {'$gt': 0}}]},
            {'$and': [{'second_party_id': entity_filter}, {'second_party_amount': {'$gt': 0}}]},
            {'$and': [{'corp_id': entity_filter}, {'corp_amount': {'$gt': 0}}]},
            {'tax_receiver_id': entity_filter}
        ]}
    elif tx_type == 'losses':
        journal_search = {'$or':[ 
            {'$and': [{'first_party_id': entity_filter}, {'first_party_amount': {'$lt': 0}}]},
            {'$and': [{'second_party_id': entity_filter}, {'second_party_amount': {'$lt': 0}}]},
            {'$and': [{'corp_id': entity_filter}, {'corp_amount': {'$lt': 0}}]},
        ]}
    elif tx_type == 'neutral':
        journal_search = {'$or':[ 
            {'$and': [{'first_party_id': entity_filter}, {'first_party_amount': {'$eq': 0}}]},
            {'$and': [{'second_party_id': entity_filter}, {'second_party_amount': {'$eq': 0}}]},
            {'$and': [{'corp_id': entity_filter}, {'corp_amount': {'$eq': 0}}]},
            {'context_id': entity_filter}
        ]}
    return journal_search

def process_common_fields(entry):
    entry['date'] = datetime.fromtimestamp(entry['date'], timezone.utc).strftime("%Y-%m-%d %X")
    conditional_decode(entry, 'tax_receiver_')
    conditional_decode(entry, 'first_party_')
    conditional_decode(entry, 'second_party_')
    conditional_decode(entry, 'corp_')
    context_decode(entry)