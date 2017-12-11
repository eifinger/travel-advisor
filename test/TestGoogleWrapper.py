import unittest
import os

from GoogleWrapper import GoogleWrapper


class TestGoogleWrapper(unittest.TestCase):

    def test_api_key_in_environment(self):
        self.assertIsNotNone(os.environ.get('GOOGLE_MAPS_API_TOKEN'))

    def test_get_distance_matrix(self):
        origin = 'Mainz'
        destination = 'SVA GmbH, Borsigstraße, Wiesbaden'
        gmaps = GoogleWrapper()
        result = gmaps.get_distance_matrix(origin=origin, destination=destination)
        self.assertIn("distance",result)
        self.assertNotEqual("",result["distance"])
        self.assertIn("duration", result)
        self.assertNotEqual("", result["duration"])
        self.assertIn("duration_in_traffic", result)
        self.assertNotEqual("", result["duration_in_traffic"])

    def test_multiple_locations(self):
        origin = 'Mainz'
        gmaps = GoogleWrapper()
        result = gmaps.get_geocode_for_location(origin)
        print(result)