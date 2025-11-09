from abc import ABC, abstractmethod
from typing import Dict, Any
from PIL import Image

class ICaptionGeneration(ABC):
    def __init__(self, model_id: str, device: str, **kwargs):
        self.model_id = model_id
        self.device = device
        self.kwargs = kwargs
        self._initialized = False

    @abstractmethod
    def initialize(self, **kwargs):
        pass

    @abstractmethod
    def is_ready(self) -> bool:
        pass
    
    @abstractmethod
    def generate_caption(
            self,
            image: Image.Image = None,
            prompt: str = None,
            **kwargs: Dict[str, Any]
        ) -> str:
        pass
