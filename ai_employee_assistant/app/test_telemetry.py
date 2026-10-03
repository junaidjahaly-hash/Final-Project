import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

class MockPosthog:
    def __init__(self, *args, **kwargs): pass
    def capture(self, *args, **kwargs): pass
sys.modules["posthog"] = MockPosthog()
sys.modules["posthog.client"] = MockPosthog()

from app.rag import collection
