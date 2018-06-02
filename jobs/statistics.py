from jobs import shared
from jobs.shared import logger

from app.flask_shared_modules import rq
from app.flask_shared_modules import r

@rq.job
def update_statistics():
    update_top_character_wallet()
    update_top_corp_wallet()
    
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
                                    '$max': 
                                        ['$wallets.0', '$wallets.1', '$wallets.2', '$wallets.3',
                                          '$wallets.4', '$wallets.5', '$wallets.6'] 
                                },
                                'name': '$name',
                                'id': '$id'
                            }}
    aggregate_sort = { '$sort': {'max_wallet': -1} }
    aggregate_limit = { '$limit': 1 }
    top_wallet_cursor = shared.db.entities.aggregate([match_filter, max_wallet_projection, aggregate_sort, aggregate_limit])
    if top_wallet_cursor is None:
        return
    
    for x in top_wallet_cursor:
        top_wallet = x
    r.hset('top_corp_wallet', 'name', top_wallet['name'])
    r.hset('top_corp_wallet', 'id', top_wallet['id'])
    r.hset('top_corp_wallet', 'wallet', top_wallet['max_wallet'])
    