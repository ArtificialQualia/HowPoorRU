"""
 Main entry point into webapp.
 sets up Flask, initializes all the modules needed, and registers the routes
"""

import pymongo

from flask import Flask

import config

from app.sso import sso_pages
from app.routes import main_pages
from app.flask_shared_modules import login_manager
from app.flask_shared_modules import mongo
from app.flask_shared_modules import rq

from jobs import wallet_refresh
from jobs import public_info_refresh
from jobs import statistics

from datetime import datetime

# -----------------
# Globals for flask, also see app/flask_shared_modules.py
# -----------------

# Create main flask app
app = Flask(__name__)
app.config.from_object(config)

# Initialize database connection
mongo.init_app(app)

# Initialize LoginManager, this for used for managing user sessions
login_manager.init_app(app)

# Initialize RedisQueue, used for jobs
rq.init_app(app)

# To prevent the job queue having a lot of duplicates on startup, cancel all existing jobs
for job in rq.get_scheduler().get_jobs():
    rq.get_scheduler().cancel(job)
    job.cancel()

# Schedule all rq background jobs
statistics.update_statistics.schedule(datetime.utcnow(), job_id="update_statistics", interval=62)
wallet_refresh.process_character_wallets.schedule(datetime.utcnow(), job_id="process_character_wallets", interval=120)
wallet_refresh.process_corp_wallets.schedule(datetime.utcnow(), job_id="process_corp_wallets", interval=300)
# Public info refresh can take a long time, so it is given a timeout longer than the default
public_info_refresh.update_all_public_info.schedule(datetime.utcnow(), job_id="update_all_public_info", interval=3600, timeout=7200)

# create indexes in database, runs on every startup to prevent manual db setup and ensure compliance
# if this is a production server, then we must run this with @postfork so it runs after uwsgi forks
# processes so that it has access to app_context(), in development servers it can be run directly
def ensure_db_indexes():
    with app.app_context():
        mongo.db.entities.create_index('id', unique=True)
        mongo.db.journals.create_index([('id', pymongo.DESCENDING)], unique=True)
        mongo.db.journals.create_index([('first_party_id', pymongo.ASCENDING), ('id', pymongo.DESCENDING)], unique=True)
        mongo.db.journals.create_index([('second_party_id', pymongo.ASCENDING), ('id', pymongo.DESCENDING)], unique=True)
        mongo.db.journals.create_index([('tax_receiver_id', pymongo.ASCENDING), ('id', pymongo.DESCENDING)], unique=True,
                                       partialFilterExpression={ 'tax_receiver_id': { '$exists': True } })
        mongo.db.journals.create_index([('context.id', pymongo.ASCENDING), ('id', pymongo.DESCENDING)], unique=True,
                                       partialFilterExpression={ 'context.id': { '$exists': True } })
        mongo.db.journals.create_index([('first_party_corp_id', pymongo.ASCENDING), ('id', pymongo.DESCENDING)], unique=True,
                                       partialFilterExpression={ 'first_party_corp_id': { '$exists': True } })
        mongo.db.journals.create_index([('second_party_corp_id', pymongo.ASCENDING), ('id', pymongo.DESCENDING)], unique=True,
                                       partialFilterExpression={ 'second_party_corp_id': { '$exists': True } })
try:
    from uwsgidecorators import postfork
    @postfork
    def postfork_ensure_db_indexes():
        ensure_db_indexes()
except ImportError as e:
    ensure_db_indexes()

# Register all our blueprints (routes that come from other files)
# this could theoretically be changed to mount the routes on other endpoints
app.register_blueprint(sso_pages)
app.register_blueprint(main_pages)

# End Globals

#profiler code for testing, disabled unless we need to performance test
#from werkzeug.contrib.profiler import ProfilerMiddleware
#app.config['PROFILE'] = True
#app.wsgi_app = ProfilerMiddleware(app.wsgi_app, restrictions=[20])

if __name__ == '__main__':
    app.run(port=config.PORT, host=config.HOST)