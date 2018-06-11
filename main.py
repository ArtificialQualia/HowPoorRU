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

statistics.update_statistics.schedule(datetime.utcnow(), job_id="update_statistics", interval=62, ttl=61)
wallet_refresh.process_character_wallets.schedule(datetime.utcnow(), job_id="process_character_wallets", interval=120, ttl=100)
wallet_refresh.process_corp_wallets.schedule(datetime.utcnow(), job_id="process_corp_wallets", interval=300, ttl=240)
public_info_refresh.update_all_public_info.schedule(datetime.utcnow(), job_id="update_all_public_info", interval=3600, ttl=600, timeout=7200)

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
            mongo.db.journals.create_index([('context_id', pymongo.ASCENDING), ('id', pymongo.DESCENDING)], unique=True,
                                           partialFilterExpression={ 'context_id': { '$exists': True } })
            mongo.db.journals.create_index([('first_party_corp_id', pymongo.ASCENDING), ('id', pymongo.DESCENDING)], unique=True,
                                           partialFilterExpression={ 'first_party_corp_id': { '$exists': True } })
            mongo.db.journals.create_index([('second_party_corp_id', pymongo.ASCENDING), ('id', pymongo.DESCENDING)], unique=True,
                                           partialFilterExpression={ 'second_party_corp_id': { '$exists': True } })
except ImportError as e:
    print('can\'t import uwsgidecorators, if this is a dev environment, please run DB setup manually')

app.register_blueprint(sso_pages)
app.register_blueprint(main_pages)

# End Globals

if __name__ == '__main__':
    app.run(port=config.PORT, host=config.HOST)