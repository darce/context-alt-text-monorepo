"""
Attention Optimizer Interfaces

This module defines the port interfaces for attention optimization strategies
in the Entity Identifier API, following the hexagonal architecture pattern.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, Any, Optional, List
from contextlib import contextmanager
import torch

from shared.enums.attention_backend import AttentionBackend


@dataclass
class AttentionCapabilities:
    """Describes the capabilities of an attention optimizer."""
    backend: AttentionBackend
    available: bool
    version: Optional[str] = None
    supports_devices: List[str] = None
    speed_improvement: Optional[float] = None  # Multiplier compared to eager attention
    compatibility_notes: str = ""
    requirements: List[str] = None
    
    def __post_init__(self):
        if self.supports_devices is None:
            self.supports_devices = []
        if self.requirements is None:
            self.requirements = []


@dataclass
class AttentionConfig:
    """Configuration for attention optimization."""
    # Preferred backends in order of preference
    preferred_backends: List[AttentionBackend] = None
    
    # Force a specific backend (overrides preference)
    force_backend: Optional[AttentionBackend] = None
    
    # Device-specific backend restrictions
    device_restrictions: Dict[str, List[AttentionBackend]] = None
    
    # Whether to fallback to eager attention if no optimized backend is available
    fallback_to_eager: bool = True
    
    # Whether to log backend selection decisions
    log_selection: bool = True
    
    # Whether to benchmark optimizers for speed measurements
    enable_benchmarking: bool = True
    
    def __post_init__(self):
        if self.preferred_backends is None:
            self.preferred_backends = [
                AttentionBackend.FLASH_ATTENTION_V2,
                AttentionBackend.FLASH_ATTENTION_V1,
                AttentionBackend.SDPA,
                AttentionBackend.EAGER
            ]
        
        if self.device_restrictions is None:
            self.device_restrictions = {
                'cpu': [AttentionBackend.SDPA, AttentionBackend.EAGER],
                'mps': [AttentionBackend.SDPA, AttentionBackend.EAGER],
                'cuda': [
                    AttentionBackend.FLASH_ATTENTION_V2,
                    AttentionBackend.FLASH_ATTENTION_V1,
                    AttentionBackend.SDPA,
                    AttentionBackend.EAGER
                ]
            }


class IAttentionOptimizer(ABC):
    """Interface for attention optimization strategies."""
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Get the optimizer name."""
        pass
    
    @abstractmethod
    def is_available(self, device: str) -> bool:
        """Check if the optimizer is available for the given device."""
        pass
    
    @abstractmethod
    def get_capabilities(self, device: str) -> AttentionCapabilities:
        """Get the capabilities of this optimizer for the given device."""
        pass
    
    @abstractmethod
    def configure_model_args(self, model_args: Dict[str, Any], device: str) -> Dict[str, Any]:
        """Configure model loading arguments for this optimizer."""
        pass
    
    @abstractmethod
    def apply_runtime_optimizations(self, model: torch.nn.Module, device: str) -> torch.nn.Module:
        """Apply runtime optimizations to the model."""
        pass
    
    @abstractmethod
    @contextmanager
    def get_context_manager(self, device: str):
        """Get a context manager for optimized inference."""
        pass
    
    @property
    @abstractmethod
    def backend_type(self) -> AttentionBackend:
        """Get the backend type this optimizer implements."""
        pass


class IAttentionOptimizerManager(ABC):
    """Interface for managing attention optimization strategies."""
    
    @abstractmethod
    def get_best_optimizer(self, device: str) -> IAttentionOptimizer:
        """Get the best available optimizer for the given device."""
        pass
    
    @abstractmethod
    def get_all_capabilities(self, device: str) -> Dict[AttentionBackend, AttentionCapabilities]:
        """Get capabilities for all optimizers on the given device."""
        pass
    
    @abstractmethod
    def configure_model_args(self, model_args: Dict[str, Any], device: str) -> Dict[str, Any]:
        """Configure model arguments with the best optimizer."""
        pass
    
    @abstractmethod
    def optimize_model(self, model: torch.nn.Module, device: str) -> torch.nn.Module:
        """Apply runtime optimizations to the model."""
        pass
    
    @abstractmethod
    def get_inference_context(self, device: str):
        """Get context manager for optimized inference."""
        pass
