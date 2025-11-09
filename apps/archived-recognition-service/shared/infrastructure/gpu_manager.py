"""
GPU Core Module - Centralized GPU Detection and Configuration
"""

import os
import json
import logging
from pathlib import Path
from typing import Optional, Dict, Tuple, List, Any
from dataclasses import dataclass
from enum import Enum
from shared.config.settings import get_config  # <-- Use canonical config loader
from shared.config.config_service import ConfigService
from shared.enums.gpu_architecture import GPUArchitecture

logger = logging.getLogger(__name__)


@dataclass
class GPUInfo:
    """Comprehensive GPU information."""
    name: str
    compute_capability: Tuple[int, int]
    architecture: GPUArchitecture
    memory_gb: float
    supports_flash_v1: bool
    supports_flash_v2: bool
    recommended_attention: str
    device_index: int = 0


@dataclass
class DeviceInfo:
    """Complete device information."""
    best_device: str
    cuda_available: bool
    mps_available: bool
    gpu_info: Optional[GPUInfo]
    device_count: int = 0


class GPUManager:
    """
    Centralized GPU detection and configuration management.
    
    This class provides a single source of truth for all GPU-related operations,
    replacing duplicate functionality across multiple modules.
    """
    
    def __init__(self):
        self._device_cache: Optional[DeviceInfo] = None
        self._gpu_info_cache: Optional[GPUInfo] = None
        
    def clear_cache(self):
        """Clear all cached GPU detection results."""
        self._device_cache = None
        self._gpu_info_cache = None
    
    def clear_gpu_memory_cache(self):
        """Clear GPU memory cache to free up unused memory."""
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                logger.info("🗑️ [GPU] Memory cache cleared")
                return True
            else:
                logger.debug("[GPU] CUDA not available - no memory cache to clear")
                return False
        except Exception as e:
            logger.warning(f"[GPU] Failed to clear GPU memory cache: {e}")
            return False
    
    def _classify_architecture(self, major: int, minor: int) -> GPUArchitecture:
        """Classify GPU architecture based on compute capability."""
        capability = major + (minor / 10.0)
        if capability >= 9.0:
            return GPUArchitecture.HOPPER
        elif capability >= 8.9:
            return GPUArchitecture.ADA_LOVELACE
        elif capability >= 8.0:
            return GPUArchitecture.AMPERE
        elif capability >= 7.5:
            return GPUArchitecture.TURING
        else:
            return GPUArchitecture.UNKNOWN
    
    def _determine_flash_attention_support(self, major: int, minor: int) -> Tuple[bool, bool]:
        """Determine Flash Attention support levels."""
        capability = major + (minor / 10.0)
        supports_flash_v1 = capability >= 7.5  # Turing and newer
        supports_flash_v2 = capability >= 8.0  # Ampere and newer
        return supports_flash_v1, supports_flash_v2
    
    def _get_recommended_attention(self, major: int, minor: int, model_name: str = "") -> str:
        """Get recommended attention implementation for GPU."""
        capability = major + (minor / 10.0)
        if "phi3" in model_name.lower():
            return "eager"
        if capability >= 8.0:
            return "flash_attention_2"
        elif capability >= 7.5:
            return "sdpa"
        else:
            return "eager"
    
    def detect_gpu_capability(self) -> Optional[Tuple[int, int]]:
        """
        Detect GPU compute capability.
        
        Returns:
            Tuple of (major, minor) compute capability or None if no CUDA GPU
        """
        try:
            import torch
            if not torch.cuda.is_available():
                return None
                
            device = torch.cuda.current_device()
            major, minor = torch.cuda.get_device_capability(device)
            logger.debug(f"GPU compute capability: {major}.{minor}")
            return (major, minor)
            
        except ImportError:
            logger.debug("PyTorch not available for GPU detection")
            return None
        except Exception as e:
            logger.warning(f"Failed to detect GPU compute capability: {e}")
            return None
    
    def get_gpu_info(self, model_name: str = "") -> Optional[GPUInfo]:
        """
        Get comprehensive GPU information.
        
        Args:
            model_name: Model name for attention configuration
            
        Returns:
            GPUInfo object with detailed GPU information or None if no GPU
        """
        if self._gpu_info_cache is not None and not model_name:
            return self._gpu_info_cache
            
        try:
            import torch
            if not torch.cuda.is_available():
                return None
                
            device = torch.cuda.current_device()
            name = torch.cuda.get_device_name(device)
            major, minor = torch.cuda.get_device_capability(device)
            memory_gb = torch.cuda.get_device_properties(device).total_memory / (1024**3)
            
            architecture = self._classify_architecture(major, minor)
            supports_flash_v1, supports_flash_v2 = self._determine_flash_attention_support(major, minor)
            recommended_attention = self._get_recommended_attention(major, minor, model_name)
            
            gpu_info = GPUInfo(
                name=name,
                compute_capability=(major, minor),
                architecture=architecture,
                memory_gb=memory_gb,
                supports_flash_v1=supports_flash_v1,
                supports_flash_v2=supports_flash_v2,
                recommended_attention=recommended_attention,
                device_index=device
            )
            
            self._gpu_info_cache = gpu_info
            return gpu_info
            
        except ImportError:
            logger.debug("PyTorch not available for GPU info")
            return None
        except Exception as e:
            logger.warning(f"Failed to get GPU info: {e}")
            return None
    
    def get_device_info(self) -> DeviceInfo:
        """
        Get comprehensive device information including GPU, CUDA, and MPS availability.
        
        Returns:
            DeviceInfo object with complete device information
        """
        try:
            import torch
            
            cuda_available = torch.cuda.is_available()
            mps_available = hasattr(torch.backends, 'mps') and torch.backends.mps.is_available()
            device_count = torch.cuda.device_count() if cuda_available else 0
            
            # Determine best device
            if cuda_available:
                best_device = 'cuda'
            elif mps_available:
                best_device = 'mps'
            else:
                best_device = 'cpu'
            
            # Get GPU info if available
            gpu_info = self.get_gpu_info() if cuda_available else None
            
            return DeviceInfo(
                best_device=best_device,
                cuda_available=cuda_available,
                mps_available=mps_available,
                gpu_info=gpu_info,
                device_count=device_count
            )
            
        except ImportError:
            logger.debug("PyTorch not available for device info")
            return DeviceInfo(
                best_device='cpu',
                cuda_available=False,
                mps_available=False,
                gpu_info=None,
                device_count=0
            )
        except Exception as e:
            logger.warning(f"Failed to get device info: {e}")
            return DeviceInfo(
                best_device='cpu',
                cuda_available=False,
                mps_available=False,
                gpu_info=None,
                device_count=0
            )
    
    def detect_best_device(self) -> str:
        """
        Detect the best available device for model inference.
        
        Returns:
            The best available device ('cuda', 'mps', or 'cpu')
        """
        device_info = self.get_device_info()
        return device_info.best_device
    
    def validate_device(self, device: str) -> bool:
        """
        Validate that a device is available.
        
        Args:
            device: Device to validate ('cuda', 'mps', 'cpu')
            
        Returns:
            True if device is available, False otherwise
        """
        device_info = self.get_device_info()
        
        if device == 'cuda':
            return device_info.cuda_available
        elif device == 'mps':
            return device_info.mps_available
        elif device == 'cpu':
            return True
        else:
            return False
    
    def resolve_device_spec(self, device_spec: str) -> str:
        """
        Resolve a device specification to an actual device.
        
        Args:
            device_spec: Device specification ('auto', 'cuda', 'mps', 'cpu')
            
        Returns:
            Resolved device name
        """
        if device_spec == 'auto':
            return self.detect_best_device()
        elif self.validate_device(device_spec):
            return device_spec
        else:
            logger.warning(f"Device {device_spec} not available, falling back to CPU")
            return 'cpu'
    
    def supports_flash_attention_v1(self) -> bool:
        """Check if Flash Attention v1 is supported."""
        gpu_info = self.get_gpu_info()
        return gpu_info.supports_flash_v1 if gpu_info else False
    
    def supports_flash_attention_v2(self) -> bool:
        """Check if Flash Attention v2 is supported."""
        gpu_info = self.get_gpu_info()
        return gpu_info.supports_flash_v2 if gpu_info else False
    
    def supports_triton(self) -> bool:
        """Check if Triton fused attention is supported. (Deprecated, always False)"""
        return False
    
    def get_optimized_settings(self, model_name: str = "phi3") -> Dict[str, str]:
        """
        Get optimized settings for the current GPU and model.
        Follows DRY principles and 12-factor app configuration standards.
        """
        gpu_info = self.get_gpu_info(model_name)
        config_service = ConfigService()
        config = config_service.get_section('runtime_optimizations')
        
        # Validate required config sections
        self._validate_runtime_config(config)
        
        # Determine device configuration
        if gpu_info is None:
            device_config = config["cpu_fallback"]
            device_type = "cpu"
            gpu_arch = "cpu"
        else:
            major, minor = gpu_info.compute_capability
            gpu_arch = f"{major + (minor / 10.0):.1f}"
            device_config = self._get_gpu_config(config["gpu_configs"], gpu_arch)
            device_type = "cuda"
        
        # Build settings using device configuration
        return self._build_settings_dict(device_config, gpu_info, device_type, gpu_arch)
    
    def _validate_runtime_config(self, config: Dict) -> None:
        """Validate that required runtime configuration keys exist."""
        required_keys = ["gpu_configs", "cpu_fallback"]
        for key in required_keys:
            if key not in config:
                raise KeyError(f"Missing required config key: {key} in settings.yaml under runtime_optimizations")
    
    def _get_gpu_config(self, gpu_configs: Dict, gpu_arch: str) -> Dict:
        """Get GPU configuration for specific architecture with fallback to default."""
        if gpu_arch in gpu_configs:
            return gpu_configs[gpu_arch]
        elif "default_gpu" in gpu_configs:
            logger.warning(f"No specific config for GPU arch {gpu_arch}, using default_gpu config")
            return gpu_configs["default_gpu"]
        else:
            raise KeyError(f"Missing GPU config for architecture {gpu_arch} and no default_gpu config in settings.yaml")
    
    def _build_settings_dict(self, device_config: Dict, gpu_info: Optional[GPUInfo], device_type: str, gpu_arch: str) -> Dict[str, str]:
        """Build the settings dictionary from device configuration."""
        # Base settings that apply to all devices
        settings = {
            "GPU_ARCH": gpu_arch,
            "DEVICE": device_type,
            "RECOMMENDED_ATTENTION": device_config["recommended_attention"],
            "FLASH_ATTENTION_ENABLED": str(device_config["flash_attention_enabled"]).lower(),
            "ENABLE_MEMORY_OPTIMIZATION": str(device_config["enable_memory_optimization"]).lower(),
        }
        
        # Add GPU-specific settings
        if gpu_info is not None and device_type == "cuda":
            major, minor = gpu_info.compute_capability
            arch_list = self._generate_torch_cuda_arch_list(major, minor)
            settings.update({
                "TORCH_CUDA_ARCH_LIST": ";".join(arch_list),
                "SUPPORTS_FLASH_ATTENTION_V1": str(gpu_info.supports_flash_v1).lower(),
                "SUPPORTS_FLASH_ATTENTION_V2": str(gpu_info.supports_flash_v2).lower(),
                "CUDA_MEMORY_FRACTION": str(device_config["cuda_memory_fraction"]),
                "MAX_SPLIT_SIZE_MB": str(device_config["max_split_size_mb"]),
            })
        else:
            # CPU fallback values
            settings.update({
                "TORCH_CUDA_ARCH_LIST": "",
                "SUPPORTS_FLASH_ATTENTION_V1": "false",
                "SUPPORTS_FLASH_ATTENTION_V2": "false",
                "CUDA_MEMORY_FRACTION": str(device_config.get("cuda_memory_fraction", "0.0")),
                "MAX_SPLIT_SIZE_MB": str(device_config.get("max_split_size_mb", "128")),
            })
        
        # Triton is deprecated, always false
        settings["SUPPORTS_TRITON"] = "false"
        
        return settings
    
    def _generate_torch_cuda_arch_list(self, major: int, minor: int) -> List[str]:
        """Generate appropriate TORCH_CUDA_ARCH_LIST for compute capability."""
        capability = major + (minor / 10.0)
        if capability >= 9.0:
            return ["7.5", "8.0", "8.6", "8.9", "9.0"]
        elif capability >= 8.9:
            return ["7.5", "8.0", "8.6", "8.9"]
        elif capability >= 8.6:
            return ["7.5", "8.0", "8.6"]
        elif capability >= 8.0:
            return ["7.5", "8.0"]
        elif capability >= 7.5:
            return ["7.5"]
        else:
            return []
    
    def get_attention_config(self, model_name: str = "phi3") -> Dict:
        """
        Get the recommended attention configuration for the current device.
        """
        gpu_info = self.get_gpu_info()
        if gpu_info is None:
            return {
                "attn_implementation": "eager",
                "flash_attention_enabled": False,
                "recommended_attention": "eager"
            }
        settings = self.get_optimized_settings(model_name)
        return {
            "attn_implementation": settings.get("RECOMMENDED_ATTENTION", "eager"),
            "flash_attention_enabled": settings.get("FLASH_ATTENTION_ENABLED", "false").lower() == "true",
            "recommended_attention": settings.get("RECOMMENDED_ATTENTION", "eager")
        }
    
    def get_environment_variables(self) -> Dict[str, str]:
        """
        Get all GPU-related environment variables.
        
        Returns:
            Dictionary of environment variables ready for export
        """
        return self.get_optimized_settings()
    
    def export_environment_file(self, output_file: str, model_name: str = "phi3") -> bool:
        """
        Export GPU configuration to a bash-sourceable file.
        
        Args:
            output_file: Path to output file
            model_name: Model name for optimization
        
        Returns:
            True if successful, False otherwise
        """
        try:
            settings = self.get_optimized_settings(model_name)
            device_info = self.get_device_info()
            
            gpu_arch = "cpu"
            if device_info.gpu_info:
                major, minor = device_info.gpu_info.compute_capability
                gpu_arch = f"{major + (minor / 10.0):.1f}"
            
            # Write to file
            with open(output_file, 'w') as f:
                f.write("#!/bin/bash\n")
                f.write("# Auto-generated GPU configuration from consolidated gpu_core\n")
                f.write(f"# Generated for architecture: {gpu_arch}\n")
                f.write(f"# Device: {device_info.best_device}\n\n")
                
                # Export all environment variables
                for key, value in settings.items():
                    f.write(f'export {key}="{value}"\n')
            
            logger.info(f"📝 Exported GPU configuration to {output_file}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to export environment file: {e}")
            return False

    def log_gpu_info(self):
        """Log comprehensive GPU information for debugging."""
        device_info = self.get_device_info()
        
        logger.info(f"🔧 Best Device: {device_info.best_device}")
        logger.info(f"🔧 CUDA Available: {device_info.cuda_available}")
        logger.info(f"🔧 MPS Available: {device_info.mps_available}")
        
        if device_info.gpu_info:
            gpu = device_info.gpu_info
            logger.info(f"🔧 GPU: {gpu.name}")
            logger.info(f"🔧 Compute Capability: {gpu.compute_capability[0]}.{gpu.compute_capability[1]}")
            logger.info(f"🔧 Architecture: {gpu.architecture.value}")
            logger.info(f"🔧 Memory: {gpu.memory_gb:.1f} GB")
            logger.info(f"🔧 Flash Attention v2: {gpu.supports_flash_v2}")
            logger.info(f"🔧 Recommended Attention: {gpu.recommended_attention}")
        else:
            logger.info("🔧 No GPU detected, using CPU")


# Global singleton instance
_gpu_manager: Optional[GPUManager] = None


def get_gpu_manager() -> GPUManager:
    """Get the global GPU manager instance."""
    global _gpu_manager
    if _gpu_manager is None:
        _gpu_manager = GPUManager()
    return _gpu_manager
