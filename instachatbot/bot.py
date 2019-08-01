import time
import logging
import requests

from instabot.api import api
from instabot.bot.bot_support import extract_urls

from instachatbot.nodes import Node, MenuNode, QuestionnaireNode
from instachatbot.state import Conversation
from instachatbot.storage import Storage


class API(api.API):
    def __init__(self, device=None, base_path=''):
        # Setup device and user_agent
        device = device or api.devices.DEFAULT_DEVICE
        self.device_settings = api.devices.DEVICES[device]
        self.user_agent = api.config.USER_AGENT_BASE.format(
            **self.device_settings)
        self.base_path = base_path
        self.is_logged_in = False
        self.last_response = None
        self.last_json = None
        self.total_requests = 0
        self.logger = logging.getLogger('instabot')


class InstagramChatBot:
    def __init__(self, menu: MenuNode, storage: Storage = None):
    # def __init__(self, menu: QuestionnaireNode, storage: Storage = None):
        self.logger = logging.getLogger('InstagramChatBot')
        self._api = API()
        self.menu_node = menu
        self._last_message_timestamp = {}
        self.conversation = Conversation(menu, storage)
        self.user_id = None
        self.arrival = None
        self.departure = None
        self.response = None

    def login(self, username, password, proxy=None):
        self._api.login(username, password, proxy=proxy, use_cookie=False)
        self.user_id = self._api.user_id

    def start(self, polling_interval=1.5):
        start_timestamp = time.time() * 1000000

        while True:
            time.sleep(polling_interval)

            # approve pending threads
            self._api.get_pending_inbox()
            for thread in self._api.last_json['inbox']['threads']:
                self._api.approve_pending_thread(thread['thread_id'])

            # process messages
            self._api.getv2Inbox()

            for message in self.parse_messages(
                    self._api.last_json, start_timestamp):
                self.logger.debug('Got message from %s: %s',
                                  message['from'], message['text'])
                context = {
                    'bot': self
                }
                self.handle_message(message, context)

    def stop(self):
        self._api.logout()

    def parse_messages(self, body, start_timestamp):
        threads = body['inbox']['threads']
        for thread in threads:
            if thread.get('is_group'):
                continue

            thread_id = thread['thread_id']
            last_seen_timestamp = thread.get(
                'last_seen_at', {}).get(
                    str(self.user_id), {}).get('timestamp', 0)
            if last_seen_timestamp:
                last_seen_timestamp = int(last_seen_timestamp)

            last_seen_timestamp = max(
                last_seen_timestamp,
                self._last_message_timestamp.get(thread_id, 0))

            items = thread.get('items')
            users = {user['pk']: user['username'] for user in thread['users']}
            users[body['viewer']['pk']] = body['viewer']['username']
            for item in items:

                if start_timestamp > item['timestamp']:
                    continue
                if last_seen_timestamp >= item['timestamp']:
                    continue

                self._last_message_timestamp[thread_id] = item['timestamp']

                yield {
                    'id': str(item['item_id']),
                    'date': item['timestamp'],
                    'type': item['item_type'],
                    'text': item.get('text'),
                    # Собираем геолокацию
                    'location': {
                        'lat': item.get('media_share', {}).get('location', {}).get('lat', None),
                        'lng': item.get('media_share', {}).get('location', {}).get('lng', None)
                    },
                    # Собираем геолокацию
                    'from': {
                        'id': str(item['user_id']),
                        'username': users.get(item['user_id'])
                    },
                    'chat': {
                        'id': str(thread_id),
                        'title': thread['thread_title'],
                        'type': thread['thread_type'],
                    }
                }

    def handle_message(self, message, context):
        chat_id = message['chat']['id']
        state = self.conversation.get_state(chat_id) or {}
        node: Node = state.get('node')

        while not node:
            if (message['text'] and 'new departure' in message['text'].lower()) or (self.response and 'didn\'t find' in self.response):
                message['text'] = '2'
                node = self.menu_node
                break
            if not self.arrival:
                if message['type'] == 'media_share':
                    if not all([message['location']['lat'], message['location']['lng']]):
                        self.response = 'Sorry, I haven\'t yet learned to find places without geotags... Try another media, please! 🌎'
                        break
                        """
                        try to determine it
                        if location is determined:
                            continue
                        else:
                            return False
                        """
                    else:
                        self.arrival = self.get_iata_code_from_gps(message['location']['lat'],
                                                                   message['location']['lng'])
                else:
                    self.response = 'Sorry, I haven\'t yet learned to hold a conversation... Share media and I\'ll try to find tickets there! 💬'
                    break
            if not self.departure:
                message['text'] = '2'
                node = self.menu_node
                break
            if self.departure == self.arrival:
                self.response = 'Are you trying to travel without leaving home? Departure and arrival must be different! 😏'
                break
            if self.departure and self.arrival and self.departure != self.arrival:
                self.response = self.get_search_link(self.departure, self.arrival)
                break

        if self.response:
            self.send_direct_message(user_id=message['from']['id'], text=self.response)
            self.arrival = None
            self.response = None

        # node: Node = state.get('node') or self.menu_node

        if node != None:
            jump = node.handle(message, state, context)
            self.conversation.save_state(chat_id, state)
            if jump:
                self.handle_message(message, context)

            if not state['node']:
                self.handle_message(message, context)

    def get_user_id_from_username(self, username):
        self._api.search_username(username)
        if "user" in self._api.last_json:
            return str(self._api.last_json["user"]["pk"])
        else:
            return None

    def send_direct_message(self, user_id, text):
        logging.debug('Sending message to %s: %s', user_id, text)
        urls = extract_urls(text)
        item_type = 'link' if urls else 'text'
        self._api.send_direct_item(item_type, users=[user_id], text=text, urls=urls)

    def send_direct_photo(self, user_id, image_path):
        logging.debug('Sending photo to %s: %s', user_id, image_path)
        self._api.send_direct_item(item_type='photo', users=[user_id], filepath=image_path)

    @staticmethod
    def get_iata_code_from_city(city):
        url = f'http://aviation-edge.com/v2/public/autocomplete?key=3d986c-70d142&city={city.lower()}'
        try:
            answer = requests.get(url).json()
            result = answer.get('cities', {})[0].get('codeIataCity')
        except Exception:
            result = None
        return result

    @staticmethod
    def get_iata_code_from_gps(lat, lng):
        url = f'http://aviation-edge.com/v2/public/nearby?key=3d986c-70d142&lat={lat}&lng={lng}&distance=100'
        try:
            answer = requests.get(url).json()
            result = answer[0].get('codeIataCity')
        except Exception:
            result = None
        return result

    @staticmethod
    def get_search_link(departure, arrival):
        # return f'https://www.skyscanner.com/transport/flights/{departure}/{arrival}/' if departure and arrival else 'Sorry, can\'t find the location!'
        return f'https://lets.travelwith.ai/{departure}/{arrival}/' if departure and arrival else 'Sorry, can\'t find the location!'
