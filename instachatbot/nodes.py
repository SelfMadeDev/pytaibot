from functools import partial
from typing import List


class Node:

    """Base node"""
    steps = ()

    def handle(self, message, state, context):
        step_index = state.get('step') or 0
        if step_index < len(self.steps):
            step = self.steps[step_index]
            jump = step(message, state, context)
            if jump:
                return jump

        step_index += 1

        if step_index >= len(self.steps):
            state.update(node=None, step=0)
        else:
            state.update(node=self, step=step_index)


class DummyNode(Node):
    """Empty node, doesn't do anything"""

    @property
    def steps(self):
        return [self.skip]

    def skip(self, message, state, context):
        pass


class MessageNode(Node):
    """Send text or picture to user

    :param text: text to send
    :type text: str
    :param image: filepath to JPG image
    :type image: str
    """

    def __init__(self, text=None, image=None):

        self.text = text
        self.image = image
        if not (text or image):
            raise ValueError('text or image required')

    @property
    def steps(self):
        return [self.send_message]

    def send_message(self, message, state, context):
        bot = context['bot']
        if self.image:
            bot.send_direct_photo(
                user_id=message['from']['id'],
                image_path=self.image)
        if self.text:
            bot.send_direct_message(
                user_id=message['from']['id'], text=self.text)


TextNode = MessageNode


class MenuItem:
    """Nodes wrapper for adding menu"""

    def __init__(self, caption, node):
        self.caption = caption
        self.node = node


class MenuNode(Node):
    """Root node for adding menu"""

    def __init__(self, header, items: List[MenuItem], error_message=''):
        self.items = items
        self.header = header
        self.error_message = error_message

    @property
    def steps(self):
        # return [self.show_menu, self.select_menu]
        return [self.check_arrival, self.check_departure]

    def check_arrival(self, message, state, context):
        bot = context['bot']
        #
        arrival = state.get('arrival')
        departure = state.get('departure')
        #
        if not arrival:
            if message['text'] and message['text'].lower() == 'new':
                state.update(node=self.items[1].node, step=0)
                return True
            elif message['type'] == 'media_share' and not bot.flag:
                if not all([message['location']['lat'], message['location']['lng']]):
                    answer = 'Sorry, I haven\'t yet learned to find places without geotags... ' \
                             'Try another media, please! 🌎'
                else:
                    arrival = bot.get_iata_code_from_gps(bot.key, message['location']['lat'], message['location']['lng'])
                    state.update(arrival=arrival, node=bot.menu_node, step=1)  # check_departure
                    return True
            else:
                if not departure:
                    answer = 'Hey! It\'s simple as one-two-three:\n' \
                             '1️⃣Find inspiring travel photo or video on Instagram\n' \
                             '2️⃣Share the content with me via direct message\n' \
                             '3️⃣Get a link to the cheapest flights to exact location from the content\n' \
                             'Just do it! We both know you can... 😉'
                else:
                    answer = 'Where would you like to travel next time? 🌎\n' \
                             'To change the departure type "new" (without quotes) 🛫'
            bot.send_direct_message(user_id=message['from']['id'], text=answer)
        else:
            state.update(node=bot.menu_node, step=1) #check_departure
            return True

    def check_departure(self, message, state, context):
        bot = context['bot']
        #
        arrival = state.get('arrival')
        departure = state.get('departure')
        #
        if arrival:
            if departure:
                if arrival != departure:
                    link = bot.get_search_link(departure, arrival)
                    answer = f'I hope this is what you\'re looking for: {link}'
                else:
                    answer = 'Are you trying to travel without leaving home? ' \
                             'Departure and arrival must be different! 😏'
                bot.try_again(user_id=message['from']['id'], text=answer, num_of_try=0)
                arrival = None
                state.update(arrival=arrival)
            else:
                state.update(node=self.items[1].node, step=0)
                return True
        else:
            state.update(node=bot.menu_node, step=0)
            return True


class QuestionnaireNode(Node):
    def __init__(self, questions: List[str], admin_username, header='',
                 response=''):
        self.response = response
        self.admin_username = admin_username
        self.questions = questions
        self.header = header
        self.steps = [
            partial(self.ask_question, question=question)
            for question in self.questions]
        self.steps.append(self.process_answers)

    def ask_question(self, message, state, context, question):
        bot = context['bot']
        step_index = state.get('step') or 0
        if step_index == 0:
            state['questionnaire'] = []
            if self.header:
                bot.send_direct_message(user_id=message['from']['id'],
                                        text=self.header)
        else:
            state['questionnaire'][-1]['answer'] = message['text']

        state['questionnaire'].append({'question': question})
        bot.send_direct_message(user_id=message['from']['id'],
                                text=question)

    def process_answers(self, message, state, context):
        response = self.header
        state['questionnaire'][-1]['answer'] = message['text']
        # text = '\n\n'.join([
        #     '{}\n{}'.format(item['question'], item['answer'])
        #     for item in state['questionnaire']])
        bot = context['bot']

        for item in state['questionnaire']:
            answer = item['answer']
            if all(x.isalpha() or x.isspace() for x in answer):
                result = bot.get_iata_code_from_city(bot.key, answer)
                response = None
                if not result:
                    response = f'Sorry, I can\'t find airport near {answer}. Let\'s try another one? 😞'
                if 'departure' in item['question']:
                    departure = result
                    state.update(departure=departure)
                elif 'arrival' in item['question']:
                    arrival = result
                    state.update(arrival=arrival)

        del state['questionnaire']

        # user_id = bot.get_user_id_from_username(self.admin_username)
        # bot.send_direct_message(
        #     user_id, '@' + message['from']['username'] + '\n' + text)

        if response:
            bot.send_direct_message(
                user_id=message['from']['id'], text=response)


class NotifyAdminNode(Node):
    def __init__(self, text, notification, admin_username):
        self.text = text
        self.admin_username = admin_username
        self.notification = notification

    @property
    def steps(self):
        return [self.notify_admin]

    def notify_admin(self, message, state, context):
        bot = context['bot']
        user_id = bot.get_user_id_from_username(self.admin_username)
        if user_id:
            bot.send_direct_message(
                user_id,
                self.notification + '\n' + '@' + message['from']['username'])

        bot.send_direct_message(user_id=message['from']['id'], text=self.text)
