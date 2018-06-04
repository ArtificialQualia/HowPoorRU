from jobs import shared
from jobs.shared import logger
from jobs import wallet_refresh
from app.flask_shared_modules import rq

@rq.job(result_ttl=500)
def update_entity(character_id=None):
    try:
        logger.debug('start one-off info refresh for ' + str(character_id))
    
        shared.user_update(character_id)
        
        character_filter = {'id': character_id}
        user_doc = shared.db.entities.find_one(character_filter)
        
        if 'corporation_id' in user_doc:
            shared.corp_update(user_doc['corporation_id'])
        
        if 'alliance_id' in user_doc:
            shared.alliance_update(user_doc['alliance_id'])
            
        wallet_refresh.process_character(user_doc)
        wallet_refresh.process_corp(user_doc)
        
        logger.debug('finished one-off info refresh for ' + str(character_id))
    except Exception as e:
        logger.exception(e)
        return
