import configparser
import os
import time
import threading
import json
import sys
import logging

from slackclient import SlackClient
from watson_developer_cloud import ConversationV1

from GoogleWrapper import GoogleWrapper
from TravelRequest import TravelRequest
from User import User

class TravelAdvisor:
    logger = logging.getLogger(__name__)
    BOT_NAME = "travel-advisor"
    WATSON_CONVERSATION_VERSION = '2017-05-26'
    MESSAGES_CONFIG_FILE = "messages.conf"
    INTENTS_CONFIG_FILE = "intents.conf"
    USES_WATSON = True

    CHECK_TRAVEL_DELAY = 60.0*2
    MAX_TRAVEL_CHECKS = 3600/CHECK_TRAVEL_DELAY

    def __init__(self):
        if not os.environ.get('SLACK_BOT_TOKEN'):
            sys.exit("No environment variable \"SLACK_BOT_TOKEN\" found.")
        self.slack_client = SlackClient(os.environ.get('SLACK_BOT_TOKEN'))
        if not self.slack_client:
            sys.exit("Could not instantiate slack client. Wrong Token?")

        self.BOT_ID = self._get_bot_id()
        self.AT_BOT = "<@" + self.BOT_ID + ">"

        if not os.environ.get('GOOGLE_MAPS_API_TOKEN'):
            sys.exit("No environment variable \"GOOGLE_MAPS_API_TOKEN\" found.")
        self.gmaps = GoogleWrapper(os.environ.get('GOOGLE_MAPS_API_TOKEN'))
        if not self.gmaps:
            sys.exit("Could not instantiate Google Maps client. Wrong Token?")

        if not os.getenv('VCAP_SERVICES'):
            self.logger.warning("No VCAP_SERVICES found. Running without Bluemix Services.")
            self.USES_WATSON = False
            self.logger.warning("USES_WATSON is {}".format(self.USES_WATSON))
        else:
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
                if output and 'text' in output and self.AT_BOT in output['text']:
                    # return text after the @ mention, whitespace removed
                    return output['text'].split(self.AT_BOT)[1].strip().lower(), \
                           output['channel'], output['user'], True
                else:
                    if output and 'channel' in output and not isinstance(output['channel'],dict) and output['channel'].startswith("D") \
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
                self.logger.info("say hello intent detected")
                self.send_message(eval(self.messages.get("DEFAULT","SAY_HELLO")), channel)
        else:
            intent = self.get_watson_intent(command)
            if intent == self.intents.get("DEFAULT","WHEN_SHOULD_I_LEAVE"):
                if user_id in self.users:
                    user = self.users.get(user_id)
                    if user.context == User.CONTEXT_REQUEST_RUNNING:
                        self.already_existing_request(user, channel)
                else:
                    new_user = User(user_id)
                    self.users[user_id] = new_user
                    new_user.name = self.get_user_name(user_id)
                    new_user.add_travel_request(TravelRequest(channel))
                    new_user.context = User.CONTEXT_REQUEST_STARTED
                    self.ask_for_origin(channel)
            elif intent == self.intents.get("DEFAULT","CANCEL_REQUEST"):
                if user_id in self.users:
                    user = self.users.get(user_id)
                    user.travel_request.user = None
                    user.travel_request = None
                    user.context = User.CONTEXT_NONE
                    self.users.pop(user_id)
                    response = eval(self.messages.get("DEFAULT", "REQUEST_CANCELLED"))
                    self.send_message(response, channel)
                else:
                    response = eval(self.messages.get("DEFAULT", "UNKOWN_USER"))
                    self.send_message(response, channel)
            elif user_id in self.users:
                user = self.users.get(user_id)
                if user.context == User.CONTEXT_REQUEST_STARTED:
                    user.context = User.CONTEXT_ORIGIN_SUPPLIED
                    self.handle_origin_supplied(user, command, channel)
                elif user.context == User.CONTEXT_ORIGIN_SUPPLIED:
                    if self.is_number(command):
                        if int(command) > 0 and len(user.origins) >= int(command)-1:
                            user.travel_request.origin = user.origins[int(command)-1]
                            user.context = User.CONTEXT_ORIGIN_SELECTED
                            self.ask_for_destination(channel)
                        else:
                            response = eval(self.messages.get("DEFAULT", "SELECTION_OUT_OF_BOUNDS"))
                            response.format(len(user.origins)-1)
                            self.send_message(response, channel)
                    else:
                        response = eval(self.messages.get("DEFAULT", "SELECTION_OUT_OF_BOUNDS"))
                        response.format(len(user.origins) - 1)
                        self.send_message(response, channel)
                elif user.context == User.CONTEXT_ORIGIN_SELECTED:
                    user.context = User.CONTEXT_DESTINATION_SUPPLIED
                    self.handle_destination_supplied(user, command, channel)
                elif user.context == User.CONTEXT_DESTINATION_SUPPLIED:
                    if self.is_number(command):
                        if int(command) > 0 and len(user.destinations) >= int(command) - 1:
                            user.travel_request.destination = user.destinations[int(command)-1]
                            user.context = User.CONTEXT_DESTINATION_SELECTED
                            user.travel_request.check_current_travel(self.gmaps)
                            self.ask_for_target_duration(user, channel)
                        else:
                            response = eval(self.messages.get("DEFAULT", "SELECTION_OUT_OF_BOUNDS"))
                            response.format(len(user.destinations)-1)
                            self.send_message(response, channel)
                    else:
                        response = eval(self.messages.get("DEFAULT", "SELECTION_OUT_OF_BOUNDS"))
                        response.format(len(user.destinations) - 1)
                        self.send_message(response, channel)
                elif user.context == User.CONTEXT_DESTINATION_SELECTED:
                    user.travel_request.target_duration = int(command) * 60
                    user.context = User.CONTEXT_REQUEST_RUNNING
                    self.handle_travel_request(user.travel_request, channel)
                else:
                    self.send_message(eval(self.messages.get("DEFAULT", "UNKOWN_COMMAND")), channel)
            else:
                self.send_message(eval(self.messages.get("DEFAULT","UNKOWN_COMMAND")), channel)

    def handle_destination_supplied(self, user, destination_supplied, channel):
        locations = self.gmaps.get_geocode_for_location(destination_supplied)
        if locations and len(locations) == 1:
            user.travel_request.destination = locations[0]
            user.context = User.CONTEXT_DESTINATION_SELECTED
            user.travel_request.check_current_travel(self.gmaps)
            self.ask_for_target_duration(user, channel)
        elif locations and len(locations) > 1:
            user.destinations = locations
            self.ask_to_choose_location(locations, channel)
        else:
            user.context = User.CONTEXT_REQUEST_STARTED
            self.no_location_found(channel)

    def handle_origin_supplied(self, user, origin_supplied, channel):
        locations = self.gmaps.get_geocode_for_location(origin_supplied)
        if locations and len(locations) == 1:
            user.travel_request.origin = locations[0]
            user.context = User.CONTEXT_ORIGIN_SELECTED
            self.ask_for_destination(channel)
        elif locations and len(locations) > 1:
            user.origins = locations
            self.ask_to_choose_location(locations, channel)
        else:
            user.context = User.CONTEXT_REQUEST_STARTED
            self.no_location_found(channel)

    def ask_to_choose_location(self, locations, channel):
        response = eval(self.messages.get("DEFAULT", "CHOOSE_LOCATION"))
        response += "\n "
        i = 1
        for location in locations:
            response += str(i) + " " + location['address'] + "\n"
            i += 1
        self.send_message(response, channel)

    def no_location_found(self, channel):
        response = eval(self.messages.get("DEFAULT", "NO_LOCATION_FOUND"))
        self.send_message(response, channel)

    def ask_for_target_duration(self, user, channel):
        response = eval(self.messages.get("DEFAULT","TRAFFIC_CONDITIONS")).format(user.travel_request.duration_in_traffic["text"], user.travel_request.duration["text"])
        self.send_message(response, channel)
        response = eval(self.messages.get("DEFAULT","TARGET_DURATION"))
        self.send_message(response, channel)

    def ask_for_destination(self, channel):
        response = eval(self.messages.get("DEFAULT","DESTINATION"))
        self.send_message(response, channel)

    def ask_for_origin(self,channel):
        response = "{} {}".format(eval(self.messages.get("DEFAULT","DETECTED_WHEN_SHOULD_I_LEAVE")), eval(self.messages.get("DEFAULT","ORIGIN")))
        self.send_message(response, channel)

    def already_existing_request(self, user, channel):
        response = "{} {} {}".format(eval(self.messages.get("DEFAULT","EXISTING_REQUEST")), eval(self.messages.get("DEFAULT","CURRENT_TRAVEL_TIME")),user.travel_request.duration_in_traffic['text'])
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
            request.user.travel_request = None
            request.user.context = User.CONTEXT_NONE
            self.users.pop(request.user.id)
            request.user = None
            message = eval(self.messages.get("DEFAULT", "TIME_EXCEEDED"))
            self.send_message(message, channel)
            return
        else:
            request.check_current_travel(self.gmaps)
            if request.duration_in_traffic['value'] <= request.target_duration:
                message = "{} nach {}".format(eval(self.messages.get("DEFAULT","YOU_CAN_LEAVE_NOW")),request.destination["address"])
                self.send_message(message, request.channel)
                self.users.pop(request.user.id)
            else:
                timer = threading.Timer(self.CHECK_TRAVEL_DELAY, self.check_travel_request, args=(request,))
                timer.start()

    def send_message(self, message, channel):
        self.slack_client.api_call("chat.postMessage", channel=channel, text=message, as_user=True)

    def get_watson_response(self, text):
        if not self.USES_WATSON:
            return None
        else:
            response_from_watson = self.conversation.message(workspace_id=self.WATSON_WORKSPACE_ID,
                                                         input={'text': text},
                                                         context={})
            return response_from_watson

    def get_watson_intent(self, text):
        response = self.get_watson_response(text)
        if response and 'intents' in response and len(response['intents']) > 0:
            return response['intents'][0]['intent']
        else:
            return None

    def is_number(self,s):
        try:
            int(s)
            return True
        except ValueError:
            return False




if __name__ == "__main__":
    # Log version (git commit hash)
    parent_dir = os.path.dirname(__file__)
    version_file = os.path.join(parent_dir, 'VERSION')
    version = None
    if os.path.isfile(version_file):
        with open(version_file) as f:
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
