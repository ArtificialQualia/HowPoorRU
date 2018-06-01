from jobs import shared
from jobs.shared import logger
from jobs import public_info_refresh
from jobs import wallet_refresh
from app.flask_shared_modules import rq

@rq.job(result_ttl=500)
def update_entity(character_id=None):
    try:
        logger.debug('start one-off info refresh for ' + str(character_id))
    
        retrieved_data = {}
        public_info_refresh.user_update(character_id, retrieved_data)
        
        if 'corporation_id' in retrieved_data:
            public_info_refresh.corp_update(retrieved_data['corporation_id'])
        
        if 'alliance_id' in retrieved_data:
            public_info_refresh.alliance_update(retrieved_data['alliance_id'])
            
        character_filter = {'id': character_id}
        user_doc = shared.db.entities.find_one(character_filter)
        wallet_refresh.process_character(user_doc)
        wallet_refresh.process_corp(user_doc)
        
        logger.debug('finished one-off info refresh for ' + str(character_id))
    except Exception as e:
        logger.exception(e)
        return
