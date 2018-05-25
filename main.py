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
from pymongo import ReturnDocument

from flask_login import LoginManager
from flask_login import current_user
from flask_login import login_required
from flask_login import login_user
from flask_login import logout_user
from flask_login.mixins import UserMixin

from flask_apscheduler import APScheduler

import config
import random
import hashlib
import hmac
from datetime import datetime
import os

app = Flask(__name__)
app.config.from_object(config)

mongo = PyMongo(app)

esiapp = App.create(config.ESI_SWAGGER_JSON)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

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
if not app.debug or os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
    scheduler = APScheduler()
    scheduler.init_app(app)
    scheduler.start()
    @scheduler.authenticate
    def authenticate(auth):
        return auth['username'] == config.SCHEDULER_AUTH_USER and auth['password'] == config.SCHEDULER_AUTH_PASSWORD

with app.app_context():
    mongo.db.users.create_index('CharacterID', unique=True)
    mongo.db.corporations.create_index('corporation_id', unique=True)
    mongo.db.alliances.create_index('alliance_id', unique=True)
    mongo.db.journals.create_index('id', unique=True)

class User(UserMixin):
    def __init__(self, character_id=None, character_data=None, auth_response=None):
        super().__init__()
        if character_id is not None:
            character_filter = {'CharacterID': character_id}
            user_data = mongo.db.users.find_one(character_filter)
            if user_data is None:
                raise Exception()
        else:
            character_filter = {'CharacterID': character_data['CharacterID']}
            character_data['tokens'] = auth_response
            character_data['tokens']['ExpiresOn'] = character_data.pop('ExpiresOn')
            update = {"$set": character_data}
            user_data = mongo.db.users.find_one_and_update(character_filter, update, return_document=ReturnDocument.AFTER, upsert=True)
        self.update_token(user_data['tokens'])
        self.character_id = user_data['CharacterID']
        self.character_name = user_data['CharacterName']
        
        
    def get_id(self):
        return self.character_id
    
    def get_sso_data(self):
        """ Little "helper" function to get formated data for esipy security
        """
        return {
            'access_token': self.access_token,
            'refresh_token': self.refresh_token,
            'expires_in': (
                self.access_token_expires - datetime.utcnow()
            ).total_seconds()
        }

    def update_token(self, token_response):
        """ helper function to update token data from SSO response """
        self.access_token = token_response['access_token']
        datetime_format = "%Y-%m-%dT%X"
        self.access_token_expires = datetime.strptime(token_response['ExpiresOn'], datetime_format)
        if 'refresh_token' in token_response:
            self.refresh_token = token_response['refresh_token']

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

    # we get the character informations
    cdata = esisecurity.verify()

    # if the user is already authed, we log him out
    if current_user.is_authenticated:
        logout_user()
    
    user = User(character_data=cdata, auth_response=auth_response)

    login_user(user)
    session.permanent = True

    return redirect(url_for("index"))

@login_manager.user_loader
def load_user(character_id):
    """ Required user loader for Flask-Login """
    return User(character_id=character_id)

@app.route('/')
@app.route('/<int:page_number>')
def index(page_number=1, *args):
    page_range_check(page_number)
    journal_cursor = mongo.db.journals.find({})
    journal_entries = []
    skip_amount = (page_number - 1) * config.PAGE_SIZE
    journal_cursor.sort('id', -1).skip(skip_amount).limit(config.PAGE_SIZE)
    for entry in journal_cursor:
        entry['first_party_id'], entry['first_party_url'] = decode_journal_party_id(entry['first_party_id'])
        entry['second_party_id'], entry['second_party_url']  = decode_journal_party_id(entry['second_party_id'])
        journal_entries.append(entry)
    return render_template('index.html', journal_entries=journal_entries, page_number=page_number)

@app.route('/character/<int:entity_id>')
@app.route('/character/<int:entity_id>/<int:page_number>')
def character(entity_id, page_number=1):
    page_range_check(page_number)
    character_filter = {'CharacterID': entity_id}
    character_data = mongo.db.users.find_one_or_404(character_filter)
    journal_search = {'$or':[ 
        {'first_party_id': entity_id},
        {'second_party_id': entity_id}
    ]}
    journal_cursor = mongo.db.journals.find(journal_search)
    skip_amount = (page_number - 1) * config.PAGE_SIZE
    journal_cursor.sort('id', -1).skip(skip_amount).limit(config.PAGE_SIZE)
    journal_entries = []
    for entry in journal_cursor:
        entry['first_party_id'], entry['first_party_url'] = decode_journal_party_id(entry['first_party_id'])
        entry['second_party_id'], entry['second_party_url']  = decode_journal_party_id(entry['second_party_id'])
        if 'tax_receiver_id' in entry:
            entry['tax_receiver_id'], entry['tax_receiver_url']  = decode_journal_party_id(entry['tax_receiver_id'])
            entry['tax'] = entry['tax'] * -1
        if entry['entity_id'] != entity_id:
            entry['amount'] = entry['amount'] * -1
            del entry['balance']
        if 'entity_id_2' in entry and entry['entity_id_2'] == entity_id:
            entry['balance'] = entry['balance_2']
        journal_entries.append(entry)
    return render_template('character.html', character_data=character_data, journal_entries=journal_entries, page_number=page_number)

@app.route('/corporation/<int:entity_id>')
@app.route('/corporation/<int:entity_id>/<int:page_number>')
def corporation(entity_id, page_number=1):
    page_range_check(page_number)
    corp_filter = {'corporation_id': entity_id}
    corp_data = mongo.db.corporations.find_one_or_404(corp_filter)
    journal_search = {'$or':[ 
        {'first_party_id': entity_id},
        {'second_party_id': entity_id},
        {'tax_receiver_id': entity_id}
    ]}
    journal_cursor = mongo.db.journals.find(journal_search)
    skip_amount = (page_number - 1) * config.PAGE_SIZE
    journal_cursor.sort('id', -1).skip(skip_amount).limit(config.PAGE_SIZE)
    journal_entries = []
    for entry in journal_cursor:
        entry['first_party_id'], entry['first_party_url'] = decode_journal_party_id(entry['first_party_id'])
        entry['second_party_id'], entry['second_party_url']  = decode_journal_party_id(entry['second_party_id'])
        if 'tax_receiver_id' in entry:
            if entry['tax_receiver_id'] == entity_id:
                entry['amount'] = entry['tax'] * -1
                entry['tax'] = entry['tax'] * -1
            entry['tax_receiver_id'], entry['tax_receiver_url']  = decode_journal_party_id(entry['tax_receiver_id'])
        if entry['entity_id'] != entity_id:
            entry['amount'] = entry['amount'] * -1
            if 'tax' in entry:
                entry['tax'] = entry['tax'] * -1
            del entry['balance']
        if 'entity_id_2' in entry and entry['entity_id_2'] == entity_id:
            entry['balance'] = entry['balance_2']
        journal_entries.append(entry)
    return render_template('corporation.html', corp_data=corp_data, journal_entries=journal_entries, page_number=page_number)

@app.route('/alliance/<int:alliance_id>')
def alliance(alliance_id):
    alliance_filter = {'alliance_id': alliance_id}
    alliance_data = mongo.db.alliances.find_one_or_404(alliance_filter)
    journal_search = {'$or':[ 
        {'first_party_id': alliance_id},
        {'second_party_id': alliance_id}
    ]}
    journal_cursor = mongo.db.journals.find(journal_search).sort('id', -1)
    journal_entries = []
    for entry in journal_cursor:
        entry['first_party_id'], entry['first_party_url'] = decode_journal_party_id(entry['first_party_id'])
        entry['second_party_id'], entry['second_party_url']  = decode_journal_party_id(entry['second_party_id'])
        journal_entries.append(entry)
    return render_template('alliance.html', alliance_data=alliance_data, journal_entries=journal_entries)

@app.route('/testself')
@login_required
def testself():
    esisecurity.update_token(current_user.get_sso_data())
    op = esiapp.op['get_characters_character_id_wallet'](
        character_id=current_user.character_id
    )
    wallet = esiclient.request(op)
    return render_template('testself.html', wallet=wallet)

def page_range_check(page_number):
    if page_number > 10 or page_number < 1:
        abort(404)
    

def decode_journal_party_id(party_id):
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
        return result['name'], url_for('alliance', alliance_id=result['alliance_id'])
    
    return party_id, None

if __name__ == '__main__':
    app.run(port=config.PORT, host=config.HOST)