from pymongo import ReturnDocument

from flask_login.mixins import UserMixin

from datetime import datetime

class User(UserMixin):
    def __init__(self, character_id=None, character_data=None, auth_response=None, mongo=None):
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
            if 'Scopes' not in character_data:
                character_data['Scopes'] = ''
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
