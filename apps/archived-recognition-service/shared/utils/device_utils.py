# Abstract device detection and context utilities for unified device handling.
import torch
from shared.config.settings import get_config

def get_available_device():
    """
    Returns the best available device: 'mps', 'cuda', or 'cpu'.
    Honors the 'hardware.enable_mps' flag in config if provided.
    """
    config = get_config()
    enable_mps = config.get('hardware', {}).get('enable_mps', True)
    if enable_mps and hasattr(torch.backends, 'mps') and torch.backends.mps.is_available() and torch.backends.mps.is_built():
        return 'mps'
    elif torch.cuda.is_available():
        return 'cuda'
    else:
        return 'cpu'

class DeviceContext:
    def __init__(self, device):
        self.device = device
    def __enter__(self):
        # Optionally set device context here
        return self.device
    def __exit__(self, exc_type, exc_val, exc_tb):
        pass
