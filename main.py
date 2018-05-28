import pymongo

from flask import Flask
from flask import render_template
from flask import url_for
from flask import abort
from flask import request
from flask import jsonify

import config
from app.sso import sso_pages
from app.flask_shared_modules import login_manager
from app.flask_shared_modules import mongo
from app.flask_shared_modules import scheduler

import itertools
import os
from collections import OrderedDict

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

# to prevent the background scheduler from running twice in Flask debug mode
# ensure the Scheduler only starts on one Flask thread
if not app.debug or os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
    scheduler.init_app(app)
    scheduler.start()
    # set authentication credentials for password-protected scheduler API
    @scheduler.authenticate
    def authenticate(auth):
        return auth['username'] == config.SCHEDULER_AUTH_USER and auth['password'] == config.SCHEDULER_AUTH_PASSWORD

# create indexes in database, runs on every startup to prevent manual db setup
# and ensure compliance
with app.app_context():
    mongo.db.entities.create_index('id', unique=True)
    mongo.db.journals.create_index([('id', pymongo.DESCENDING)], unique=True)
    mongo.db.journals.create_index([('first_party_id', pymongo.ASCENDING), ('id', pymongo.DESCENDING)], unique=True)
    mongo.db.journals.create_index([('second_party_id', pymongo.ASCENDING), ('id', pymongo.DESCENDING)], unique=True)
    mongo.db.journals.create_index([('tax_receiver_id', pymongo.ASCENDING), ('id', pymongo.DESCENDING)], unique=True,
                                   partialFilterExpression={ 'tax_receiver_id': { '$exists': True } })

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
    return jsonify(request.form)

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