import os
from instachatbot.bot import InstagramChatBot
from instachatbot.nodes import (MenuNode, MenuItem, QuestionnaireNode)
from instachatbot.storage import FileStorage

menu = MenuNode(
    'Is it departure or arrival?\n',
    [
        MenuItem(
            'departure 🛫',
            QuestionnaireNode(
                [
                    'Сity of arrival? 🛬'
                ],
                header='',
                admin_username='travelwithai',
                response='Gotcha! 😉')),
        MenuItem(
            'arrival 🛬',
            QuestionnaireNode(
                [
                    'Сity of departure? 🛫'
                ],
                header='',
                admin_username='travelwithai',
                response='Gotcha! 😉'))
    ],
    error_message='Hey! It\'s simple as one-two-three:\n' \
                  '1️⃣Find inspiring travel photo or video on Instagram\n' \
                  '2️⃣Share the content with me via direct message\n' \
                  '3️⃣Get a link to the cheapest flights to exact location from the content\n' \
                  'Just do it! We both know you can... 😉'
)

chatbot = InstagramChatBot(menu=menu, storage=FileStorage())
chatbot.login(
    key=os.environ['AE_KEY'],
    username=os.environ['IG_USERNAME'],
    password=os.environ['IG_PASSWORD'])
    # proxy=os.environ['PROXY'])
chatbot.start()