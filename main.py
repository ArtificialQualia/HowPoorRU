import pymongo
import bson

from flask import Flask
from flask import render_template
from flask import url_for
from flask import abort
from flask import request
from flask import jsonify

from flask_rq2 import cli


import config
from app.sso import sso_pages
from app.flask_shared_modules import login_manager
from app.flask_shared_modules import mongo
from app.flask_shared_modules import rq
from jobs import wallet_refresh
from jobs import public_info_refresh

import re
from collections import OrderedDict
from datetime import datetime

# -----------------
# Globals for flask
# -----------------

# Create main flask app
app = Flask(__name__)
app.config.from_object(config)

# Initialize database connection
mongo.init_app(app)

# Initialize LoginManager, this for used for managing user sessions
login_manager.init_app(app)

rq.init_app(app)
#rq.init_cli(app)

#rq_workers = []
#for x in range(config.RQ_WORKER_COUNT):
#    new_worker = cli.worker()
#    rq_workers.append(new_worker)

for job in rq.get_scheduler().get_jobs():
    rq.get_scheduler().cancel(job)
    job.cancel()

wallet_refresh.process_character_wallets.schedule(datetime.utcnow(), job_id="process_character_wallets", interval=120, ttl=100)
wallet_refresh.process_corp_wallets.schedule(datetime.utcnow(), job_id="process_corp_wallets", interval=300, ttl=240)
public_info_refresh.update_all_public_info.schedule(datetime.utcnow(), job_id="update_all_public_info", interval=3600, ttl=600)

# create indexes in database, runs on every startup to prevent manual db setup
# and ensure compliance
try:
    from uwsgidecorators import postfork
    @postfork
    def ensure_db_indexs():
        with app.app_context():
            mongo.db.entities.create_index('id', unique=True)
            mongo.db.journals.create_index([('id', pymongo.DESCENDING)], unique=True)
            mongo.db.journals.create_index([('first_party_id', pymongo.ASCENDING), ('id', pymongo.DESCENDING)], unique=True)
            mongo.db.journals.create_index([('second_party_id', pymongo.ASCENDING), ('id', pymongo.DESCENDING)], unique=True)
            mongo.db.journals.create_index([('tax_receiver_id', pymongo.ASCENDING), ('id', pymongo.DESCENDING)], unique=True,
                                           partialFilterExpression={ 'tax_receiver_id': { '$exists': True } })
except ImportError as e:
    print('can\'t import uwsgidecorators, this is probably a dev environment.  Please run DB setup manually')


app.register_blueprint(sso_pages)

# End Globals

@app.route('/')
@app.route('/<int:page_number>')
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
    # TODO: profile this
    journal_cursor.sort('id', -1).skip(skip_amount).limit(config.PAGE_SIZE)
    
    # initialize empty journal_entries to ensure something gets passed to render_template
    journal_entries = []
    for entry in journal_cursor:
        # if this corp wasn't the receiver of tax, then it had to pay out the tax
        if 'tax' in entry:
            entry['tax'] = entry['tax'] * -1
            
        # turn common line items in journal entry into proper names and generated URLs
        conditional_decode(entry, 'tax_receiver_')
        conditional_decode(entry, 'first_party_')
        conditional_decode(entry, 'second_party_')
        
        # sort the journal entry by name so line items are less random in transaction details modal
        sorted_entry = OrderedDict(sorted(entry.items(), key=lambda x: x[0]))
        
        journal_entries.append(sorted_entry)
        
    return render_template('index.html', journal_entries=journal_entries, page_number=page_number)

@app.route('/character/<int:entity_id>')
@app.route('/character/<int:entity_id>/<int:page_number>')
def character(entity_id, page_number=1):
    """ paginated character page, has character details and journal entries """
    # ensure page is in valid range
    page_range_check(page_number)
    
    # find user in database, or return a 404
    character_filter = {'id': entity_id}
    character_data = mongo.db.entities.find_one_or_404(character_filter)
    if character_data['type'] != 'character':
        abort(404)
    
    # we turn special database fields into proper names and urls
    conditional_decode(character_data, 'corporation_')
    conditional_decode(character_data, 'alliance_')
    
    # find all journal entries that this entity is involved in
    journal_search = {'$or':[ 
        {'first_party_id': entity_id},
        {'second_party_id': entity_id}
    ]}
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
        conditional_decode(entry, 'tax_receiver_')
        conditional_decode(entry, 'first_party_')
        conditional_decode(entry, 'second_party_')
        
        # sort the journal entry by name so line items are less random in transaction details modal
        sorted_entry = OrderedDict(sorted(entry.items(), key=lambda x: x[0]))
        
        journal_entries.append(sorted_entry)
        
    return render_template('character.html', entity_data=character_data, journal_entries=journal_entries, page_number=page_number)

@app.route('/corporation/<int:entity_id>')
@app.route('/corporation/<int:entity_id>/<int:page_number>')
def corporation(entity_id, page_number=1):
    """ paginated corporation page, has corp details and journal entries """
    # ensure page is in valid range
    page_range_check(page_number)
    
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
    journal_search = {'$or':[ 
        {'first_party_id': entity_id},
        {'second_party_id': entity_id},
        {'tax_receiver_id': entity_id}
    ]}
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
        conditional_decode(entry, 'tax_receiver_')
        conditional_decode(entry, 'first_party_')
        conditional_decode(entry, 'second_party_')
        
        # sort the journal entry by name so line items are less random in transaction details modal
        sorted_entry = OrderedDict(sorted(entry.items(), key=lambda x: x[0]))
        
        journal_entries.append(sorted_entry)
        
    return render_template('corporation.html', entity_data=corp_data, journal_entries=journal_entries, page_number=page_number)

@app.route('/alliance/<int:entity_id>')
@app.route('/alliance/<int:entity_id>/<int:page_number>')
def alliance(entity_id, page_number=1):
    """ paginated alliance page, has alliance details and journal entries from all corps """
    # ensure page is in valid range
    page_range_check(page_number)
    
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
    journal_search = {'$or':[ 
        {'first_party_id': { '$in': alliance_data['corps'] } },
        {'second_party_id': { '$in': alliance_data['corps'] } },
        {'tax_receiver_id': { '$in': alliance_data['corps'] } }
    ]}
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
        conditional_decode(entry, 'tax_receiver_')
        conditional_decode(entry, 'first_party_')
        conditional_decode(entry, 'second_party_')
        
        # sort the journal entry by name so line items are less random in transaction details modal
        sorted_entry = OrderedDict(sorted(entry.items(), key=lambda x: x[0]))
        
        journal_entries.append(sorted_entry)
        
    return render_template('alliance.html', entity_data=alliance_data, journal_entries=journal_entries, page_number=page_number)

@app.route('/search', methods=['POST'])
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
        one_result.append(url_for(result['type'], entity_id=result['id']))
        limited_results.append(one_result)
    return jsonify(limited_results)

def page_range_check(page_number):
    """ returns a 404 if the page is outside the supported number of pages """
    # TODO: change these to config values and ensure that value is passed to paginated.html
    if page_number > 10 or page_number < 1:
        abort(404)
        
def conditional_decode(entry, id_prefix):
    """ helper to decode entity database ids to names and urls """
    if (id_prefix + 'id') in entry:
        id_filter = {'id': entry[id_prefix + 'id']}
        result = mongo.db.entities.find_one(id_filter)
        if result is not None:
            entry[id_prefix + 'name'] = result['name']
            entry[id_prefix + 'url'] = url_for(result['type'], entity_id=result['id'])

def decode_journal_party_id(party_id):
    """ 
    looks up database ids in all databases and returns names and urls for those ids 
    
    Returns:
        Tuple (name_of_entity, url_for_entity)
        if id can't be resolved, returns (None, None)
    """
    id_filter = {'id': party_id}
    result = mongo.db.entities.find_one(id_filter)
    if result is not None:
        return result['name'], url_for(result['type'], entity_id=result['id'])
    
    return None, None

if __name__ == '__main__':
    app.run(port=config.PORT, host=config.HOST)