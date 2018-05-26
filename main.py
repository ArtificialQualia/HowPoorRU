from esipy import App
from esipy import EsiClient
from esipy import EsiSecurity
from esipy.exceptions import APIException

from flask import Flask
from flask import render_template
from flask import request
from flask import session
from flask import redirect
from flask import url_for
from flask import abort

from flask_pymongo import PyMongo

from flask_login import LoginManager
from flask_login import current_user
from flask_login import login_required
from flask_login import login_user
from flask_login import logout_user

from flask_apscheduler import APScheduler

import config
from app.user import User

import random
import hashlib
import hmac
import os
from collections import OrderedDict

# -----------------
# Globals for flask
# -----------------

# Create main flask app
app = Flask(__name__)
app.config.from_object(config)

# Initialize database connection
mongo = PyMongo(app)

# Initialize LoginManager, this for used for managing user sessions
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Initialize ESI connection, all three below globals are needed to set up ESI connection
esiapp = App.create(config.ESI_SWAGGER_JSON)

# init the security object
esisecurity = EsiSecurity(
    app=esiapp,
    redirect_uri=config.ESI_CALLBACK,
    client_id=config.ESI_CLIENT_ID,
    secret_key=config.ESI_SECRET_KEY,
    headers={'User-Agent': config.ESI_USER_AGENT}
)

# init the client
esiclient = EsiClient(
    security=esisecurity,
    cache=None,
    headers={'User-Agent': config.ESI_USER_AGENT}
)

# to prevent the background scheduler from running twice in Flask debug mode
# ensure the Scheduler only starts on one Flask thread
if not app.debug or os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
    scheduler = APScheduler()
    scheduler.init_app(app)
    scheduler.start()
    # set authentication credentials for password-protected scheduler API
    @scheduler.authenticate
    def authenticate(auth):
        return auth['username'] == config.SCHEDULER_AUTH_USER and auth['password'] == config.SCHEDULER_AUTH_PASSWORD

# create indexes in database, runs on every startup to prevent manual db setup
# and ensure compliance
with app.app_context():
    mongo.db.users.create_index('CharacterID', unique=True)
    mongo.db.corporations.create_index('corporation_id', unique=True)
    mongo.db.alliances.create_index('alliance_id', unique=True)
    mongo.db.journals.create_index('id', unique=True)

# End Globals

# -----------------------------------------------------------------------
# Login / Logout Routes
# -----------------------------------------------------------------------
def generate_token():
    """Generates a non-guessable OAuth token"""
    chars = ('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789')
    rand = random.SystemRandom()
    random_string = ''.join(rand.choice(chars) for _ in range(40))
    return hmac.new(
        config.SECRET_KEY.encode('utf-8'),
        random_string.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()


@app.route('/sso/login')
def login():
    """ this redirects the user to the EVE SSO login """
    token = generate_token()
    session['token'] = token
    scopes = []
    for scope in request.args:
        scopes.append(request.args.get(scope))
    return redirect(esisecurity.get_auth_uri(
        scopes=scopes,
        state=token,
    ))


@app.route('/sso/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for("index"))


@app.route('/sso/callback')
def callback():
    """ This is where the user comes after he logged in SSO """
    # get the code from the login process
    code = request.args.get('code')
    token = request.args.get('state')

    # compare the state with the saved token for CSRF check
    sess_token = session.pop('token', None)
    if sess_token is None or token is None or token != sess_token:
        app.logger.debug('Expected session token: ' + sess_token)
        app.logger.debug('Received session token: ' + token)
        return 'Login EVE Online SSO failed: Session Token Mismatch', 403

    # now we try to get tokens
    try:
        auth_response = esisecurity.auth(code)
    except APIException as e:
        return 'Login EVE Online SSO failed: %s' % e, 403

    # the character information is retrieved
    cdata = esisecurity.verify()

    # if the user is already authed, they are logged out
    if current_user.is_authenticated:
        logout_user()
    
    # create a user object from custom User class
    user = User(character_data=cdata, auth_response=auth_response, mongo=mongo)

    # register user with flask-login
    login_user(user)
    session.permanent = True

    # send user to main index, maybe switch this to user page?
    return redirect(url_for("index"))

@login_manager.user_loader
def load_user(character_id):
    """ Required user loader for Flask-Login """
    return User(character_id=character_id, mongo=mongo)

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
        decode_journal_parties(entry)
        
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
    character_filter = {'CharacterID': entity_id}
    character_data = mongo.db.users.find_one_or_404(character_filter)
    
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
        # this is triggered for when a database entry has multiple parties involved that have APIs
        # 'amount' is negated because the second party in a entry has the opposite of amount applied to them
        if entry['entity_id'] != entity_id:
            entry['amount'] = entry['amount'] * -1
            
        # turn common line items in journal entry into proper names and generated URLs
        decode_journal_parties(entry)
        
        # sort the journal entry by name so line items are less random in transaction details modal
        sorted_entry = OrderedDict(sorted(entry.items(), key=lambda x: x[0]))
        
        journal_entries.append(sorted_entry)
        
    return render_template('character.html', character_data=character_data, journal_entries=journal_entries, page_number=page_number)

@app.route('/corporation/<int:entity_id>')
@app.route('/corporation/<int:entity_id>/<int:page_number>')
def corporation(entity_id, page_number=1):
    """ paginated corporation page, has corp details and journal entries """
    # ensure page is in valid range
    page_range_check(page_number)
    
    # find user in database, or return a 404
    corp_filter = {'corporation_id': entity_id}
    corp_data = mongo.db.corporations.find_one_or_404(corp_filter)
    
    # we turn special database fields into proper names and urls
    conditional_decode(corp_data, 'ceo_')
    conditional_decode(corp_data, 'alliance_')
    
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
        # this is triggered for when a database entry has multiple parties involved that have APIs
        # 'amount' is negated because the second party in a entry has the opposite of amount applied to them
        if entry['entity_id'] != entity_id:
            entry['amount'] = entry['amount'] * -1
            # if this corp wasn't the receiver of tax, then it had to pay out the tax
            if 'tax' in entry and entry['tax_receiver_id'] != entity_id:
                entry['tax'] = entry['tax'] * -1
            
        # turn common line items in journal entry into proper names and generated URLs
        decode_journal_parties(entry)
        
        # sort the journal entry by name so line items are less random in transaction details modal
        sorted_entry = OrderedDict(sorted(entry.items(), key=lambda x: x[0]))
        
        journal_entries.append(sorted_entry)
        
    return render_template('corporation.html', corp_data=corp_data, journal_entries=journal_entries, page_number=page_number)

@app.route('/alliance/<int:entity_id>')
@app.route('/alliance/<int:entity_id>/<int:page_number>')
def alliance(entity_id, page_number=1):
    """ paginated alliance page, has alliance details and journal entries from all corps """
    # ensure page is in valid range
    page_range_check(page_number)
    
    # find user in database, or return a 404
    alliance_filter = {'alliance_id': entity_id}
    alliance_data = mongo.db.alliances.find_one_or_404(alliance_filter)
    
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
        # same logic as corp endpoint
        if entry['entity_id'] not in alliance_data['corps']:
            entry['amount'] = entry['amount'] * -1
            if 'tax' in entry and entry['tax_receiver_id'] not in alliance_data['corps']:
                entry['tax'] = entry['tax'] * -1
            
        # turn common line items in journal entry into proper names and generated URLs
        decode_journal_parties(entry)
        
        # sort the journal entry by name so line items are less random in transaction details modal
        sorted_entry = OrderedDict(sorted(entry.items(), key=lambda x: x[0]))
        
        journal_entries.append(sorted_entry)
        
    return render_template('alliance.html', alliance_data=alliance_data, journal_entries=journal_entries, page_number=page_number)

def page_range_check(page_number):
    """ returns a 404 if the page is outside the supported number of pages """
    # TODO: change these to config values and ensure that value is passed to paginated.html
    if page_number > 10 or page_number < 1:
        abort(404)
        
def conditional_decode(entry, id_prefix):
    """ helper to decode entity database ids to names and urls """
    if (id_prefix + 'id') in entry:
        entry[id_prefix + 'name'], entry[id_prefix + 'url'] = decode_journal_party_id(entry[id_prefix + 'id'])

def decode_journal_parties(entry):
    """ helper to decode common journal entry fields into names and urls """
    entry['entity_id'], entry['entity_url'] = decode_journal_party_id(entry['entity_id'])
    if 'entity_id_2' in entry:
        entry['entity_id_2'], entry['entity_url_2'] = decode_journal_party_id(entry['entity_id_2'])
    entry['first_party_id'], entry['first_party_url'] = decode_journal_party_id(entry['first_party_id'])
    entry['second_party_id'], entry['second_party_url']  = decode_journal_party_id(entry['second_party_id'])
    if 'tax_receiver_id' in entry:
        entry['tax_receiver_id'], entry['tax_receiver_url']  = decode_journal_party_id(entry['tax_receiver_id'])

def decode_journal_party_id(party_id):
    """ 
    looks up database ids in all databases and returns names and urls for those ids 
    
    Returns:
        Tuple (name_of_entity, url_for_entity)
        if id can't be resolved, returns (original_id, None)
    """
    character_filter = {'CharacterID': party_id}
    result = mongo.db.users.find_one(character_filter)
    if result is not None:
        return result['CharacterName'], url_for('character', entity_id=result['CharacterID'])
    
    corp_filter = {'corporation_id': party_id}
    result = mongo.db.corporations.find_one(corp_filter)
    if result is not None:
        return result['name'], url_for('corporation', entity_id=result['corporation_id'])
    
    alliance_filter = {'alliance_id': party_id}
    result = mongo.db.alliances.find_one(alliance_filter)
    if result is not None:
        return result['name'], url_for('alliance', entity_id=result['alliance_id'])
    
    return party_id, None

if __name__ == '__main__':
    app.run(port=config.PORT, host=config.HOST)