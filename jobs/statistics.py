"""
 contains job that updates statistics that get placed in the Redis cache for later consumption
 many statistics contain 'long' running or complicated queries that may require a full db scan
"""

from jobs import shared
from jobs.shared import logger

from app.flask_shared_modules import rq
from app.flask_shared_modules import r

from datetime import datetime
from datetime import timezone
from datetime import timedelta

@rq.job
def update_statistics():
    update_top_character_wallet()
    update_top_corp_wallet()
    update_top_transaction()
    
def update_top_character_wallet():
    top_wallet_cursor = shared.db.entities.find().sort([('wallet', -1)]).limit(1)
    if top_wallet_cursor is None:
        return
    
    for x in top_wallet_cursor:
        top_wallet = x
    r.hset('top_character_wallet', 'name', top_wallet['name'])
    r.hset('top_character_wallet', 'id', top_wallet['id'])
    r.hset('top_character_wallet', 'wallet', top_wallet['wallet'])
    
def update_top_corp_wallet():
    match_filter = { '$match': {
                        'wallets': {'$exists': 1}
                    }}
    max_wallet_projection = { '$project': { 
                                'max_wallet': { 
                                    '$sum': 
                                        '$wallets.balance'
                                },
                                'name': '$name',
                                'id': '$id'
                            }}
    aggregate_sort = { '$sort': {'max_wallet': -1} }
    aggregate_limit = { '$limit': 1 }
    top_wallet_cursor = shared.db.entities.aggregate([match_filter, max_wallet_projection, aggregate_sort, aggregate_limit])
    
    for top_wallet in top_wallet_cursor:
        r.hset('top_corp_wallet', 'name', top_wallet['name'])
        r.hset('top_corp_wallet', 'id', top_wallet['id'])
        r.hset('top_corp_wallet', 'wallet', top_wallet['max_wallet'])
    
def update_top_transaction():
    one_day_ago = (datetime.now(timezone.utc) - timedelta(days=1)).timestamp()
    top_tx_cursor = shared.db.journals.find({'date': {'$gte': one_day_ago}}).sort([('second_party_amount', -1)]).limit(1)
    
    for top_tx in top_tx_cursor:
        r.hset('top_tx_day', 'id', top_tx['id'])