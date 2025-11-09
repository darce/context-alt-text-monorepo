from shared.config.config_service import ConfigService
from shared.utils.device_utils import get_available_device

class ContextBuilder:
    def __init__(self, config_service=None):
        self.config_service = config_service or ConfigService()
        self.config = self.config_service.get_section('context_builder')
        self.device = get_available_device()
    
    def build(self, caption: str = None, post_body: str = None) -> str:
        """
        Combine caption and post body for use as context input.
        Trims post_body and prioritizes caption.
        """
        parts = []
        if caption:
            parts.append(f"{self.config['caption_prefix']}: {caption}")
        if post_body:
            max_length = self.config['max_excerpt_length']
            excerpt = post_body.strip()[:max_length]
            parts.append(f"{self.config['context_prefix']}: {excerpt}")
        return self.config['separator'].join(parts) if parts else ""
