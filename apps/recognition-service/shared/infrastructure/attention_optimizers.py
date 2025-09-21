#!/usr/bin/env python3
"""
Attention Optimization Implementations

This module provides concrete implementations of attention optimization strategies,
using the interfaces defined in ports.attention_optimizer_base.

The implementations include:
- Flash Attention v1/v2 support
- PyTorch native SDPA (Scaled Dot Product Attention)
- Eager attention fallback
"""

import os
import torch
import logging
import importlib.util
from typing import Dict, Any, Optional
from contextlib import contextmanager

from shared.infrastructure.ports.attention_optimizer_base import (
    IAttentionOptimizer, 
    IAttentionOptimizerManager,
    AttentionCapabilities, 
    AttentionConfig
)
from shared.enums.attention_backend import AttentionBackend
from shared.utils.device_utils import get_available_device

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logger.propagate = True


class FlashAttentionV2Optimizer(IAttentionOptimizer):
    """Flash Attention v2 optimization implementation."""
    
    @property
    def name(self) -> str:
        """Get the optimizer name."""
        return "flash_attention_2"
    
    def is_available(self, device: str) -> bool:
        """Check Flash Attention v2 availability."""
        if device in ['cpu', 'mps']:
            return False
        
        try:
            import flash_attn
            version = getattr(flash_attn, '__version__', '0.0.0')
            return version.startswith('2.') and torch.cuda.is_available()
        except ImportError:
            return False
    
    def get_capabilities(self, device: str) -> AttentionCapabilities:
        """Get Flash Attention v2 capabilities."""
        available = self.is_available(device)
        version = None
        
        if available:
            try:
                import flash_attn
                version = getattr(flash_attn, '__version__', 'unknown')
            except ImportError:
                pass
        
        # Only report measured speed improvements, no estimates
        speed_improvement = None
        if available:
            try:
                speed_improvement = self._get_measured_speedup(device)
            except Exception as e:
                logger.debug(f"Could not benchmark Flash Attention v2: {e}")
                speed_improvement = None
        
        return AttentionCapabilities(
            backend=AttentionBackend.FLASH_ATTENTION_V2,
            available=available,
            version=version,
            supports_devices=['cuda'],
            speed_improvement=speed_improvement,
            compatibility_notes="Requires CUDA compute capability >= 8.0 (A100, RTX 30/40 series)",
            requirements=["flash-attn>=2.0.0", "torch>=2.0.0", "CUDA>=11.8"]
        )
    
    def _get_measured_speedup(self, device: str) -> Optional[float]:
        """Get measured speedup from benchmarking only - no estimates."""
        if hasattr(self, '_speedup_cache') and device in self._speedup_cache:
            return self._speedup_cache[device]
        
        # Initialize cache
        if not hasattr(self, '_speedup_cache'):
            self._speedup_cache = {}
        
        try:
            # Lazy import to avoid circular dependency
            from shared.utils.attention_benchmark import AttentionBenchmarker
            benchmarker = AttentionBenchmarker(device, warmup_iterations=2, benchmark_iterations=5)
            
            # Create eager optimizer for comparison (avoid circular import)
            eager = EagerAttentionOptimizer()
            
            eager_result = benchmarker.benchmark_optimizer(eager, "small")
            flash_result = benchmarker.benchmark_optimizer(self, "small")
            
            if eager_result.success and flash_result.success:
                speedup = eager_result.avg_time_ms / flash_result.avg_time_ms
                self._speedup_cache[device] = speedup
                logger.info(f"📊 [FLASH-ATTN-V2] Measured speedup on {device}: {speedup:.2f}x")
                return speedup
        except Exception as e:
            logger.debug(f"Benchmarking failed: {e}")
        
        # Return None instead of fallback estimate if benchmarking fails
        logger.warning(f"[FLASH-ATTN-V2] Could not measure speedup on {device}")
        return None
    
    def configure_model_args(self, model_args: Dict[str, Any], device: str) -> Dict[str, Any]:
        """Configure model for Flash Attention v2."""
        if self.is_available(device):
            model_args = model_args.copy()
            model_args['attn_implementation'] = 'flash_attention_2'
            logger.info("⚡ [FLASH-ATTN-V2] Configured Flash Attention v2")
        return model_args
    
    def apply_runtime_optimizations(self, model: torch.nn.Module, device: str) -> torch.nn.Module:
        """Apply Flash Attention v2 runtime optimizations."""
        # Flash Attention v2 is typically configured at model loading time
        return model
    
    @contextmanager
    def get_context_manager(self, device: str):
        """Context manager for Flash Attention v2 inference."""
        try:
            if self.is_available(device):
                # Enable optimized attention during inference
                yield
            else:
                yield
        except Exception as e:
            logger.warning(f"Flash Attention v2 context error: {e}")
            yield
    
    @property
    def backend_type(self) -> AttentionBackend:
        return AttentionBackend.FLASH_ATTENTION_V2


class FlashAttentionV1Optimizer(IAttentionOptimizer):
    """Flash Attention v1 optimization implementation."""
    
    @property
    def name(self) -> str:
        """Get the optimizer name."""
        return "flash_attention_1"
    
    def is_available(self, device: str) -> bool:
        """Check Flash Attention v1 availability."""
        if device in ['cpu', 'mps']:
            return False
        
        try:
            import flash_attn
            version = getattr(flash_attn, '__version__', '0.0.0')
            return version.startswith('1.') and torch.cuda.is_available()
        except ImportError:
            return False
    
    def get_capabilities(self, device: str) -> AttentionCapabilities:
        """Get Flash Attention v1 capabilities."""
        available = self.is_available(device)
        version = None
        
        if available:
            try:
                import flash_attn
                version = getattr(flash_attn, '__version__', 'unknown')
            except ImportError:
                pass
        
        # Only report measured speed improvements, no estimates
        speed_improvement = None
        if available:
            try:
                speed_improvement = self._get_measured_speedup(device)
            except Exception as e:
                logger.debug(f"Could not benchmark Flash Attention v1: {e}")
                speed_improvement = None
        
        return AttentionCapabilities(
            backend=AttentionBackend.FLASH_ATTENTION_V1,
            available=available,
            version=version,
            supports_devices=['cuda'],
            speed_improvement=speed_improvement,
            compatibility_notes="Supports older GPUs including T4 (compute capability >= 7.5)",
            requirements=["flash-attn>=1.0.0,<2.0.0", "torch>=1.12.0", "CUDA>=11.6"]
        )
    
    def _get_measured_speedup(self, device: str) -> Optional[float]:
        """Get measured speedup from benchmarking only - no estimates."""
        if hasattr(self, '_speedup_cache') and device in self._speedup_cache:
            return self._speedup_cache[device]
        
        # Initialize cache
        if not hasattr(self, '_speedup_cache'):
            self._speedup_cache = {}
        
        try:
            # Lazy import to avoid circular dependency
            from shared.utils.attention_benchmark import AttentionBenchmarker
            benchmarker = AttentionBenchmarker(device, warmup_iterations=2, benchmark_iterations=5)
            
            # Create eager optimizer for comparison
            eager = EagerAttentionOptimizer()
            
            eager_result = benchmarker.benchmark_optimizer(eager, "small")
            flash_result = benchmarker.benchmark_optimizer(self, "small")
            
            if eager_result.success and flash_result.success:
                speedup = eager_result.avg_time_ms / flash_result.avg_time_ms
                self._speedup_cache[device] = speedup
                logger.info(f"📊 [FLASH-ATTN-V1] Measured speedup on {device}: {speedup:.2f}x")
                return speedup
        except Exception as e:
            logger.debug(f"Benchmarking failed: {e}")
        
        # Return None instead of fallback estimate if benchmarking fails
        logger.warning(f"[FLASH-ATTN-V1] Could not measure speedup on {device}")
        return None
    
    def configure_model_args(self, model_args: Dict[str, Any], device: str) -> Dict[str, Any]:
        """Configure model for Flash Attention v1."""
        if self.is_available(device):
            model_args = model_args.copy()
            model_args['attn_implementation'] = 'flash_attention_1'
            logger.info("⚡ [FLASH-ATTN-V1] Configured Flash Attention v1")
        return model_args
    
    def apply_runtime_optimizations(self, model: torch.nn.Module, device: str) -> torch.nn.Module:
        """Apply Flash Attention v1 runtime optimizations."""
        return model
    
    @contextmanager
    def get_context_manager(self, device: str):
        """Context manager for Flash Attention v1 inference."""
        try:
            yield
        except Exception as e:
            logger.warning(f"Flash Attention v1 context error: {e}")
            yield
    
    @property
    def backend_type(self) -> AttentionBackend:
        return AttentionBackend.FLASH_ATTENTION_V1


class SDPAOptimizer(IAttentionOptimizer):
    """Scaled Dot Product Attention (PyTorch native) optimization implementation."""
    
    @property
    def name(self) -> str:
        """Get the optimizer name."""
        return "sdpa"
    
    def is_available(self, device: str) -> bool:
        """ TODO: No effect noted on CPU"""
        """Check SDPA availability."""
        try:
            # SDPA is available in PyTorch 2.0+
            has_sdpa = hasattr(torch.nn.functional, 'scaled_dot_product_attention')
            
            # Exclude MPS only for Phi-3 models due to known compatibility issues
            if device.lower() == 'mps':
                try:
                    from shared.config.config_service import ConfigService
                    config_service = ConfigService()
                    return not config_service.is_phi3_model()
                except Exception as e:
                    # Log the specific error for debugging
                    logger.debug(f"Could not determine model type for SDPA compatibility: {e}")
                    # Default to False (allow SDPA) rather than True (block SDPA)
                    # This is less conservative but more practical for non-Phi3 models
                    return False
                
            return has_sdpa
        except Exception:
            return False
    
    def get_capabilities(self, device: str) -> AttentionCapabilities:
        """Get SDPA capabilities with real benchmark measurements only."""
        available = self.is_available(device)
        
        # Only report real measured speed improvements, no fallback estimates
        speed_improvement = None
        if available:
            speed_improvement = self._get_measured_speedup(device)
        
        return AttentionCapabilities(
            backend=AttentionBackend.SDPA,
            available=available,
            version=torch.__version__ if available else None,
            supports_devices=['cuda', 'mps', 'cpu'],
            speed_improvement=speed_improvement,
            compatibility_notes="PyTorch native implementation, broadly compatible",
            requirements=["torch>=2.0.0"]
        )
    
    def _get_measured_speedup(self, device: str) -> Optional[float]:
        """Get measured speedup from benchmarking only - no fallback estimates."""
        try:
            # Check if we have cached benchmark results
            if hasattr(self, '_speedup_cache') and device in self._speedup_cache:
                return self._speedup_cache[device]
            # Initialize cache
            if not hasattr(self, '_speedup_cache'):
                self._speedup_cache = {}
            # Run quick benchmark
            from shared.utils.attention_benchmark import AttentionBenchmarker
            benchmarker = AttentionBenchmarker(device, warmup_iterations=2, benchmark_iterations=5)
            # Create optimizers for comparison
            eager = EagerAttentionOptimizer()
            # Quick benchmark using small config
            eager_result = benchmarker.benchmark_optimizer(eager, "small")
            sdpa_result = benchmarker.benchmark_optimizer(self, "small")
            if eager_result.success and sdpa_result.success:
                speedup = eager_result.avg_time_ms / sdpa_result.avg_time_ms
                self._speedup_cache[device] = speedup
                logger.info(f"📊 [SDPA] Measured speedup on {device}: {speedup:.2f}x")
                return speedup
            else:
                logger.warning(f"📊 [SDPA] Could not measure speedup on {device} - benchmarking failed")
                return None
        except Exception as e:
            logger.warning(f"Failed to benchmark SDPA speedup on {device}: {e}")
            return None
    
    def configure_model_args(self, model_args: Dict[str, Any], device: str) -> Dict[str, Any]:
        """Configure model for SDPA."""
        if self.is_available(device):
            model_args = model_args.copy()
            model_args['attn_implementation'] = 'sdpa'
            logger.info(f"🔧 [SDPA] Configured Scaled Dot Product Attention for {device}")
        return model_args
    
    def apply_runtime_optimizations(self, model: torch.nn.Module, device: str) -> torch.nn.Module:
        """Apply SDPA runtime optimizations."""
        if self.is_available(device):
            try:
                # SDPA is automatically used when attn_implementation='sdpa'
                # Set optimization flags based on device
                if device == 'cuda':
                    # Enable CUDA-specific optimizations
                    if hasattr(torch.backends.cuda, 'enable_math_sdp'):
                        torch.backends.cuda.enable_math_sdp(True)
                    if hasattr(torch.backends.cuda, 'enable_flash_sdp'):
                        torch.backends.cuda.enable_flash_sdp(True)
                    if hasattr(torch.backends.cuda, 'enable_mem_efficient_sdp'):
                        torch.backends.cuda.enable_mem_efficient_sdp(True)
                    logger.info(f"🔧 [SDPA] Enabled CUDA optimizations for {device}")
                elif device == 'mps':
                    # MPS-specific optimizations
                    if hasattr(torch.backends.mps, 'enable_math_sdp'):
                        torch.backends.mps.enable_math_sdp(True)
                    logger.info(f"🔧 [SDPA] Enabled MPS optimizations for {device}")
                else:
                    # CPU optimizations
                    if hasattr(torch.backends.cpu, 'enable_math_sdp'):
                        torch.backends.cpu.enable_math_sdp(True)
                    logger.info(f"🔧 [SDPA] Enabled CPU optimizations for {device}")
                
                # Store device type for context manager
                model._sdpa_device = device
                logger.info(f"🔧 [SDPA] SDPA configured for {device}")
                
            except Exception as e:
                logger.warning(f"SDPA runtime optimization failed: {e}")
        
        return model
    
    @contextmanager
    def get_context_manager(self, device: str):
        """Context manager for SDPA inference optimizations."""
        try:
            if self.is_available(device):
                # PyTorch automatically uses optimized SDPA when attn_implementation='sdpa'
                # The context manager just ensures SDPA is being used
                logger.debug(f"Using SDPA context for {device}")
                yield
            else:
                logger.debug(f"SDPA not available for {device}, using fallback")
                yield
        except Exception as e:
            # Special handling for MPS-specific errors with Phi-3 models
            is_phi3 = False
            try:
                from shared.config.config_service import ConfigService
                config_service = ConfigService()
                is_phi3 = config_service.is_phi3_model()
            except Exception:
                pass
                
            if device.lower() == 'mps' and is_phi3 and 'Placeholder storage' in str(e):
                logger.warning(f"MPS SDPA compatibility issue detected with Phi-3 model: {e}. Using eager attention fallback.")
            else:
                logger.warning(f"SDPA context manager error: {e}")
            yield
    
    @property
    def backend_type(self) -> AttentionBackend:
        return AttentionBackend.SDPA


class EagerAttentionOptimizer(IAttentionOptimizer):
    """Fallback eager attention implementation."""
    
    @property
    def name(self) -> str:
        """Get the optimizer name."""
        return "eager"
    
    def is_available(self, device: str) -> bool:
        """Eager attention is always available."""
        return True
    
    def get_capabilities(self, device: str) -> AttentionCapabilities:
        """Get eager attention capabilities."""
        return AttentionCapabilities(
            backend=AttentionBackend.EAGER,
            available=True,
            version=torch.__version__,
            supports_devices=['cuda', 'mps', 'cpu'],
            speed_improvement=1.0,  # Baseline for comparison only
            compatibility_notes="Standard PyTorch implementation, always available",
            requirements=["torch"]
        )
    
    def configure_model_args(self, model_args: Dict[str, Any], device: str) -> Dict[str, Any]:
        """Configure model for eager attention."""
        model_args = model_args.copy()
        model_args['attn_implementation'] = 'eager'
        return model_args
    
    def apply_runtime_optimizations(self, model: torch.nn.Module, device: str) -> torch.nn.Module:
        """No runtime optimizations for eager attention."""
        return model
    
    @contextmanager
    def get_context_manager(self, device: str):
        """Simple context manager for eager attention."""
        yield
    
    @property
    def backend_type(self) -> AttentionBackend:
        return AttentionBackend.EAGER


class AttentionOptimizerManager(IAttentionOptimizerManager):
    """
    Manager for attention optimization strategies.
    
    This class provides a high-level interface for selecting and applying
    the best available attention optimization for a given device and model.
    """
    
    def __init__(self, config: Optional[AttentionConfig] = None):
        self.config = config or AttentionConfig()
        self.optimizers = {
            AttentionBackend.FLASH_ATTENTION_V2: FlashAttentionV2Optimizer(),
            AttentionBackend.FLASH_ATTENTION_V1: FlashAttentionV1Optimizer(),
            AttentionBackend.SDPA: SDPAOptimizer(),
            AttentionBackend.EAGER: EagerAttentionOptimizer(),
        }
        self._selected_optimizers: Dict[str, IAttentionOptimizer] = {}
    
    def get_best_optimizer(self, device: str) -> IAttentionOptimizer:
        """
        Get the best available attention optimizer for the given device.
        
        Args:
            device: Target device ('cuda', 'mps', 'cpu')
            
        Returns:
            Best available attention optimizer
        """
        if device in self._selected_optimizers:
            return self._selected_optimizers[device]
        
        # Check if a specific backend is forced
        if self.config.force_backend:
            optimizer = self.optimizers.get(self.config.force_backend)
            if optimizer and optimizer.is_available(device):
                self._selected_optimizers[device] = optimizer
                if self.config.log_selection:
                    logger.info(f"🎯 [ATTENTION] Forced backend {self.config.force_backend.value} for {device}")
                return optimizer
            else:
                logger.warning(f"Forced backend {self.config.force_backend.value} not available for {device}")
        
        # Get device-specific allowed backends
        allowed_backends = self.config.device_restrictions.get(device, self.config.preferred_backends)
        
        # Find the best available optimizer
        for backend in self.config.preferred_backends:
            if backend in allowed_backends:
                optimizer = self.optimizers.get(backend)
                if optimizer and optimizer.is_available(device):
                    self._selected_optimizers[device] = optimizer
                    if self.config.log_selection:
                        capabilities = optimizer.get_capabilities(device)
                        speedup = capabilities.speed_improvement
                        if speedup is not None:
                            logger.info(f"✅ [ATTENTION] Selected {backend.value} for {device} (measured {speedup:.1f}x speedup)")
                        else:
                            logger.info(f"✅ [ATTENTION] Selected {backend.value} for {device} (no speedup measurement available)")
                    return optimizer
        
        # Fallback to eager if enabled
        if self.config.fallback_to_eager:
            optimizer = self.optimizers[AttentionBackend.EAGER]
            self._selected_optimizers[device] = optimizer
            if self.config.log_selection:
                logger.info(f"🔄 [ATTENTION] Fallback to eager attention for {device}")
            return optimizer
        
        raise RuntimeError(f"No suitable attention optimizer found for device {device}")
    
    def get_all_capabilities(self, device: str) -> Dict[AttentionBackend, AttentionCapabilities]:
        """Get capabilities for all attention optimizers on the given device."""
        capabilities = {}
        for backend, optimizer in self.optimizers.items():
            capabilities[backend] = optimizer.get_capabilities(device)
        return capabilities
    
    def configure_model_args(self, model_args: Dict[str, Any], device: str) -> Dict[str, Any]:
        """Configure model arguments with the best attention optimizer."""
        optimizer = self.get_best_optimizer(device)
        return optimizer.configure_model_args(model_args, device)
    
    def optimize_model(self, model: torch.nn.Module, device: str) -> torch.nn.Module:
        """Apply runtime optimizations to the model."""
        optimizer = self.get_best_optimizer(device)
        return optimizer.apply_runtime_optimizations(model, device)
    
    def get_inference_context(self, device: str):
        """Get context manager for optimized inference."""
        optimizer = self.get_best_optimizer(device)
        return optimizer.get_context_manager(device)
    
    def log_attention_summary(self, device: str):
        """Log a comprehensive summary of attention capabilities."""
        logger.info(f"🔍 [ATTENTION] Summary for device: {device}")
        
        capabilities = self.get_all_capabilities(device)
        selected_optimizer = self.get_best_optimizer(device)
        
        # Log available backends
        available_backends = [
            backend.value for backend, caps in capabilities.items() 
            if caps.available
        ]
        logger.info(f"📋 [ATTENTION] Available backends: {', '.join(available_backends)}")
        
        # Log selected backend details
        selected_caps = capabilities[selected_optimizer.backend_type]
        logger.info(f"⭐ [ATTENTION] Selected: {selected_caps.backend.value}")
        if selected_caps.speed_improvement is not None:
            logger.info(f"🚀 [ATTENTION] Measured speedup: {selected_caps.speed_improvement:.1f}x")
        else:
            logger.info(f"🚀 [ATTENTION] Speedup: Not measured yet")
        if selected_caps.compatibility_notes:
            logger.info(f"ℹ️ [ATTENTION] Notes: {selected_caps.compatibility_notes}")


# Global attention manager instance
_attention_manager: Optional[AttentionOptimizerManager] = None


def get_attention_manager(config: Optional[AttentionConfig] = None) -> AttentionOptimizerManager:
    """Get or create the global attention optimizer manager."""
    global _attention_manager
    if _attention_manager is None:
        _attention_manager = AttentionOptimizerManager(config)
    return _attention_manager


def optimize_model_attention(model_args: Dict[str, Any], device: str, config: Optional[AttentionConfig] = None) -> Dict[str, Any]:
    """
    Convenience function to optimize model arguments for attention.
    
    Args:
        model_args: Model loading arguments
        device: Target device
        config: Optional attention configuration
        
    Returns:
        Optimized model arguments
    """
    manager = get_attention_manager(config)
    return manager.configure_model_args(model_args, device)


def create_inference_context(device: str, config: Optional[AttentionConfig] = None):
    """
    Convenience function to create an optimized inference context.
    
    Args:
        device: Target device
        config: Optional attention configuration
        
    Returns:
        Context manager for optimized inference
    """
    manager = get_attention_manager(config)
    return manager.get_inference_context(device)
