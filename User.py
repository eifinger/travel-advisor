class User:

    CONTEXT_NONE = 0
    CONTEXT_REQUEST_STARTED = 1
    CONTEXT_ORIGIN_SUPPLIED = 2
    CONTEXT_ORIGIN_SELECTED = 3
    CONTEXT_DESTINATION_SUPPLIED = 4
    CONTEXT_DESTINATION_SELECTED = 5
    CONTEXT_REQUEST_RUNNING = 6


    def __init__(self, id, name=None):
        self.id = id
        self.name = name
        self.travel_request = None
        self.context = self.CONTEXT_NONE
        self.origins = None
        self.destinations = None

    def add_travel_request(self, request):
        self.travel_request = request
        request.user = self
