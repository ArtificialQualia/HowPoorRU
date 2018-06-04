from jobs import shared
from jobs.shared import logger

from app.flask_shared_modules import rq

@rq.job
def update_all_public_info():
    try:
        logger.debug('start public info refresh')
    
        entity_cursor = shared.db.entities.find({})
        for entity_doc in entity_cursor:
            if 'type' not in entity_doc:
                logger.error('DB entry ' + entity_doc.id + ' does not have a type')
                continue
            elif entity_doc['type'] == 'character':
                shared.user_update(entity_doc['id'])
            elif entity_doc['type'] == 'corporation':
                shared.corp_update(entity_doc['id'])
            elif entity_doc['type'] == 'alliance':
                shared.alliance_update(entity_doc['id'])
    
        logger.debug('done public info refresh')
    except Exception as e:
        logger.exception(e)
        return
        