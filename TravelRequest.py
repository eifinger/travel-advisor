import uuid
from datetime import datetime

class TravelRequest:

    def __init__(self, channel, origin = None, destination= None, target_duration=None):
        self.id = uuid.uuid4()
        self.last_checked = None
        self.origin = origin
        self.destination = destination
        self.target_duration = target_duration
        self.channel = channel
        self.distance = None
        self.duration = None
        self.duration_in_traffic = None
        self.counter = 0
        self.user = None

    def check_current_travel(self, gmaps):
        self.last_checked = datetime.now()
        self.counter += 1
        matrix = gmaps.get_distance_matrix(self.origin["geocode"], self.destination["geocode"])
        self.distance = matrix['distance']
        self.duration = matrix['duration']
        self.duration_in_traffic = matrix['duration_in_traffic']
        if not self.target_duration:
            self.target_duration = self.duration['value']
