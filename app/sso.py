"""
 Flask blueprint to handle logins/logouts and related for EVE SSO
"""

from esipy.exceptions import APIException

from flask import request
from flask import session
from flask import redirect
from flask import url_for
from flask import Blueprint
from flask import current_app

from flask_login import current_user
from flask_login import login_required
from flask_login import login_user
from flask_login import logout_user

import random
import hashlib
import hmac

import config
from app.user import User
from app.flask_shared_modules import login_manager
from app.flask_shared_modules import mongo
from app.flask_shared_modules import esisecurity
from jobs import one_off_refresh

sso_pages = Blueprint('sso_pages', __name__)

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


@sso_pages.route('/sso/login')
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


@sso_pages.route('/sso/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for("main_pages.index"))


@sso_pages.route('/sso/callback')
def callback():
    """ This is where the user comes after he logged in SSO """
    # get the code from the login process
    code = request.args.get('code')
    token = request.args.get('state')

    # compare the state with the saved token for CSRF check
    sess_token = session.pop('token', None)
    if sess_token is None or token is None or token != sess_token:
        current_app.logger.debug('Expected session token: ' + sess_token)
        current_app.logger.debug('Received session token: ' + token)
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
    
    # add one-off job to the queue to refresh ESI data for this character
    one_off_refresh.update_entity.queue(user.character_id, 
                                        job_id="one_off_refresh-for-" + str(user.character_id))

    # register user with flask-login
    login_user(user)
    session.permanent = True

    # send user to main index, maybe switch this to user page?
    return redirect(url_for("main_pages.index"))

@login_manager.user_loader
def load_user(character_id):
    """ Required user loader for Flask-Login """
    return User(character_id=character_id, mongo=mongo)

@login_manager.unauthorized_handler
def unauthorized():
    return redirect(url_for("sso_pages.login", char_scope='esi-wallet.read_character_wallet.v1', corp_scope='esi-wallet.read_corporation_wallets.v1'))