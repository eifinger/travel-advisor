class User:

    def __init__(self, id, name=None):
        self.id = id
        self.name = name
        self.travel_request = None

    def add_travel_request(self, request):
        self.travel_request = request
        request.user = self