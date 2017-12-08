import googlemaps
import os
from datetime import datetime

class GoogleWrapper:

    def __init__(self, key=os.environ.get('GOOGLE_MAPS_API_TOKEN')):
        self.gmaps = googlemaps.Client(key)

    def get_distance_matrix(self, origin, destination):
        now = datetime.now()
        matrix = self.gmaps.distance_matrix(origin,
                                            destination,
                                            mode="driving",
                                            departure_time=now,
                                            traffic_model = "best_guess")
        distance = matrix['rows'][0]['elements'][0]['distance']
        duration = matrix['rows'][0]['elements'][0]['duration']
        duration_in_traffic = matrix['rows'][0]['elements'][0]['duration_in_traffic']
        return {"distance": distance, "duration": duration, "duration_in_traffic": duration_in_traffic}

if __name__ == "__main__":
    origin = 'Mainz'
    destination ='SVA GmbH, Borsigstraße, Wiesbaden'
    gmaps = GoogleWrapper()
    result = gmaps.get_distance_matrix(origin=origin, destination=destination)
    print(result)
