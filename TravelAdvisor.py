import configparser
import os
import time
import threading
import json

from slackclient import SlackClient
from watson_developer_cloud import ConversationV1

from GoogleWrapper import GoogleWrapper
from TravelRequest import TravelRequest
from User import User

class TravelAdvisor:


    BOT_NAME = "travel-advisor"
    WATSON_CONVERSATION_VERSION = '2017-05-26'
    MESSAGES_CONFIG_FILE = "messages.conf"
    INTENTS_CONFIG_FILE = "intents.conf"

    CHECK_TRAVEL_DELAY = 60.0*2
    MAX_TRAVEL_CHECKS = 3600/CHECK_TRAVEL_DELAY

    def __init__(self):
        self.slack_client = SlackClient(os.environ.get('SLACK_BOT_TOKEN'))
        self.BOT_ID = self._get_bot_id()
        self.AT_BOT = "<@" + self.BOT_ID + ">"
        self.gmaps = GoogleWrapper(os.environ.get('GOOGLE_MAPS_API_TOKEN'))
        vcap_services = json.loads(os.getenv('VCAP_SERVICES'))
        self.WATSON_USER = vcap_services['conversation'][0]['credentials']['username']
        self.WATSON_PASSWORD = vcap_services['conversation'][0]['credentials']['password']
        self.WATSON_WORKSPACE_ID = os.environ.get('WATSON_WORKSPACE_ID')
        self.conversation = ConversationV1(
            username=self.WATSON_USER,
            password=self.WATSON_PASSWORD,
            version= self.WATSON_CONVERSATION_VERSION
        )
        self.users = {}
        self.messages = self._load_config(self.MESSAGES_CONFIG_FILE)
        self.intents = self._load_config(self.INTENTS_CONFIG_FILE)

    def _get_bot_id(self):
        """
            Identify the user ID assigned to the bot so we can identify messages.
        :return: The user id of the bot example: U79Q3RS22
        """
        api_call = self.slack_client.api_call("users.list")
        if api_call.get('ok'):
            # retrieve all users so we can find our bot
            users = api_call.get('members')
            for user in users:
                if 'name' in user and user.get('name') == self.BOT_NAME:
                    return user.get('id')

    def _load_config(self, configFile):
        parent_dir = os.path.dirname(__file__)
        config_file = os.path.join(parent_dir, configFile)
        parser = configparser.ConfigParser()
        parser.read(config_file)
        return parser

    def get_user_name(self, user_id):
        api_call = self.slack_client.api_call("users.list")
        if api_call.get('ok'):
            # retrieve all users so we can find our bot
            users = api_call.get('members')
            for user in users:
                if 'id' in user and user.get('id') == user_id:
                    return user.get('name')

    def parse_slack_output(self,slack_rtm_output):
        """
            The Slack Real Time Messaging API is an events firehose.
            this parsing function returns None unless a message is
            directed at the Bot, based on its ID.
        """
        output_list = slack_rtm_output
        if output_list and len(output_list) > 0:
            for output in output_list:
                print(output)
                print(self.AT_BOT)
                if output and 'text' in output and self.AT_BOT in output['text']:
                    # return text after the @ mention, whitespace removed
                    return output['text'].split(self.AT_BOT)[1].strip().lower(), \
                           output['channel'], output['user'], True
                else:
                    if output and 'channel' in output and output['channel'].startswith("D") \
                    and 'type' in output and output['type'] == 'message' \
                    and 'user' in output and output['user'] != self.BOT_ID:
                        return output['text'], output['channel'], output['user'], False

        return None, None, None, None

    def handle_command(self,command, user_id, channel, is_AT_bot):
        """
            Receives commands directed at the bot and determines if they
            are valid commands. If so, then acts on the commands. If not,
            returns back what it needs for clarification.
        """
        if is_AT_bot:
            intent = self.get_watson_intent(command)
            if intent == self.intents.get("DEFAULT","SAY_HELLO"):
                print("say hello intent detected")
                self.send_message(eval(self.messages.get("DEFAULT","SAY_HELLO")), channel)
        else:
            intent = self.get_watson_intent(command)
            if intent == self.intents.get("DEFAULT","WHEN_SHOULD_I_LEAVE"):
                if user_id in self.users:
                    user = self.users.get(user_id)
                    if user.travel_request:
                        self.already_existing_request(user, channel)
                else:
                    new_user = User(user_id)
                    self.users[user_id] = new_user
                    new_user.name = self.get_user_name(user_id)
                    new_user.travel_request = TravelRequest(channel)
                    self.ask_for_origin(channel)
            elif user_id in self.users:
                user = self.users.get(user_id)
                if user.travel_request:
                    if not user.travel_request.origin:
                        user.travel_request.origin = command
                        self.ask_for_destination(channel)
                    elif not user.travel_request.destination:
                        user.travel_request.destination = command
                        self.ask_for_target_duration(channel)
                    elif not user.travel_request.target_duration:
                        user.travel_request.target_duration = int(command) * 60
                        self.handle_travel_request(user.travel_request, channel)
            else:
                self.send_message(eval(self.messages.get("DEFAULT","UNKOWN_COMMAND")), channel)

    def ask_for_target_duration(self, channel):
        response = eval(self.messages.get("DEFAULT","TARGET_DURATION"))
        self.send_message(response, channel)

    def ask_for_destination(self, channel):
        response = eval(self.messages.get("DEFAULT","DESTINATION"))
        self.send_message(response, channel)

    def ask_for_origin(self,channel):
        response = "{} {}".format(eval(self.messages.get("DEFAULT","DETECTED_WHEN_SHOULD_I_LEAVE")), eval(self.messages.get("DEFAULT","ORIGIN")))
        self.send_message(response, channel)

    def already_existing_request(self, user, channel):
        response = "{}{}".format(eval(self.messages.get("DEFAULT","EXISTING_REQUEST")), eval(self.messages.get("DEFAULT","CURRENT_TRAVEL_TIME")),user.travel_request.duration_in_traffic['text'])
        self.send_message(response, channel)

    def handle_travel_request(self, request, channel):
        request.check_current_travel(self.gmaps)

        message = "{}{}".format(eval(self.messages.get("DEFAULT","CURRENT_TRAVEL_TIME")),request.duration_in_traffic['text'])
        self.send_message(message,channel)

        message = eval(self.messages.get("DEFAULT","I_WILL_NOTIFY")).format(int(request.target_duration/60))
        self.send_message(message, channel)

        self.check_travel_request(request)


    def check_travel_request(self, request):
        #Only check MAX_TRAVEL_CHECK times to prevent endless checks
        if request.counter > self.MAX_TRAVEL_CHECKS:
            return
        else:
            request.check_current_travel(self.gmaps)
            if request.duration_in_traffic['value'] <= request.target_duration:
                message = "{} nach {}".format(eval(self.messages.get("DEFAULT","YOU_CAN_LEAVE_NOW")),request.destination)
                self.send_message(message, request.channel)
            else:
                timer = threading.Timer(self.CHECK_TRAVEL_DELAY, self.check_travel_request, args=(request,))
                timer.start()

    def send_message(self, message, channel):
        self.slack_client.api_call("chat.postMessage", channel=channel, text=message, as_user=True)

    def get_watson_response(self, text):
        response_from_watson = self.conversation.message(workspace_id=self.WATSON_WORKSPACE_ID,
                                                         input={'text': text},
                                                         context={})
        return response_from_watson

    def get_watson_intent(self, text):
        response = self.get_watson_response(text)
        if 'intents' in response and len(response['intents']) > 0:
            return response['intents'][0]['intent']
        else:
            return None




if __name__ == "__main__":
    # Log version (git commit hash)
    version = None
    if os.path.isfile('VERSION'):
        with open('VERSION') as f:
            version = f.readline().replace("\n", "")
            date = f.readline().replace("\n", "")
            print("Running git commit: {}. This was last verified: {}".format(version, date))
    else:
        print("Could not find VERSION file")

    bot = TravelAdvisor()

    READ_WEBSOCKET_DELAY = 0.1  # 1 second delay between reading from firehose
    if bot.slack_client.rtm_connect():
        print("StarterBot connected and running!")
        while True:
            command, channel, user, is_AT_bot = bot.parse_slack_output(bot.slack_client.rtm_read())
            if command and channel and user:
                bot.handle_command(command, user, channel, is_AT_bot)
            time.sleep(READ_WEBSOCKET_DELAY)
    else:
        print("Connection failed. Invalid Slack token or bot ID?")
