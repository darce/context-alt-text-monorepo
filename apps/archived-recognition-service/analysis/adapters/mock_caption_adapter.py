from analysis.ports.caption_generation_base import ICaptionGeneration

class MockCaptionAdapter(ICaptionGeneration):
    def __init__(self, *args, **kwargs):
        super().__init__(model_id="mock", device="cpu")
        self._initialized = True
    def initialize(self, **kwargs):
        self._initialized = True
    def is_ready(self):
        return True
    def generate_caption(self, image, prompt=None, **kwargs):
        return "[MOCK CAPTION: Captioning disabled for test]"
