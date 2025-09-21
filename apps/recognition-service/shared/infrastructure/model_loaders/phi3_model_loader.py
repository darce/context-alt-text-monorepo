import logging
from typing import Any, Dict, Optional
from shared.infrastructure.gpu_manager import get_gpu_manager
from shared.infrastructure.attention_optimizers import get_attention_manager
from shared.utils.device_utils import get_available_device
from shared.config.config_service import ConfigService

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logger.propagate = True

def _lazy_import_torch():
    """Lazy import torch to avoid startup delays"""
    import torch
    return torch

def _lazy_import_transformers():
    """Lazy import transformers to avoid startup delays"""
    from transformers import AutoModelForCausalLM, AutoProcessor, AutoConfig
    return AutoModelForCausalLM, AutoProcessor, AutoConfig

class Phi3ModelLoader:
    def __init__(self, model_id: str, device: str = None, config: Dict[str, Any] = None, **kwargs: Dict[str, Any]):
        if device is None:
            device = get_available_device()
        self.model_id = model_id
        # Load config first, then resolve and log device (handles MPS fallback)
        self.config = config or {}
        self.device = self._resolve_device(device)
        self.kwargs = kwargs
        self.model = None
        self.processor = None
        
    def load_model(self, model_id: str, device: str = None, **kwargs: Dict[str, Any]) -> Any:
        if device is None:
            device = get_available_device()
        """Load the Phi3 vision model with optimized settings."""
        # Check MPS fallback configuration and add Phi-3 specific MPS handling
        mps_fallback_config = self.config.get('mps_fallback', {})
        disable_mps = mps_fallback_config.get('disable_mps', False)
        enable_cpu_fallback = mps_fallback_config.get('enable_cpu_fallback', True)
        
        # Phi-3.5-vision-instruct has known issues with MPS - be more aggressive about CPU fallback
        if device.lower() == 'mps' or (device.lower() == 'auto' and get_available_device() == 'mps'):
            import platform
            if platform.system() == 'Darwin':  # macOS
                logger.warning(f"[PHI3-LOADER] Phi-3.5-vision-instruct has known compatibility issues with MPS on macOS")
                if enable_cpu_fallback:
                    logger.info(f"[PHI3-LOADER] Forcing CPU fallback for better compatibility")
                    device = 'cpu'
                elif disable_mps:
                    logger.info(f"[PHI3-LOADER] MPS disabled in config, using CPU")
                    device = 'cpu'
        
        # Override device if MPS is globally disabled
        if disable_mps and device.lower() == 'mps':
            logger.info(f"[PHI3-LOADER] MPS disabled in config, falling back to CPU")
            device = 'cpu'
        
        # Re-resolve device after MPS fallback
        resolved_device = self._resolve_device(device)
        logger.info(f"[PHI3-LOADER] Device resolved for model loading: {device} -> {resolved_device}")

        if self.model is not None:
            return self.model
        try:
            # Lazy import transformers classes
            AutoModelForCausalLM, AutoProcessor, AutoConfig = self._get_transformers()
            logger.info(f"Loading Phi3 model: {model_id}")
            # Get model settings from config
            model_settings = self.config.get('model_settings', {})
            trust_remote_code = model_settings['trust_remote_code']

            # Create model configuration
            model_config = AutoConfig.from_pretrained(
                model_id,
                trust_remote_code=trust_remote_code
            )

            # Build loading arguments based on device and settings
            loading_args = self._build_loading_args(model_settings, resolved_device, trust_remote_code)
            loading_args['config'] = model_config

            # Load the model
            self.model = AutoModelForCausalLM.from_pretrained(model_id, **loading_args)

            # Handle device placement
            self.model = self._handle_device_placement(self.model, resolved_device)

            # Set to evaluation mode
            self.model.eval()

            try:
                device_info = next(self.model.parameters()).device
                logger.info(f"[PHI3] Model parameters are on device: {device_info}")
            except Exception as e:
                logger.warning(f"[PHI3] Could not determine model parameter device: {e}")
            return self.model
        except Exception as e:
            logger.error(f"Failed to load Phi3 model: {e}")
            raise

    def load_processor(self, model_id: str, **kwargs: Dict[str, Any]) -> Any:
        """Load the Phi3 processor."""
        if self.processor is not None:
            return self.processor
        try:
            # Lazy import transformers classes
            AutoModelForCausalLM, AutoProcessor, AutoConfig = self._get_transformers()

            model_settings = self.config.get('model_settings', {})
            processor_settings = self.config.get('processor_settings', {})
            trust_remote_code = processor_settings.get('trust_remote_code', model_settings['trust_remote_code'])

            # Build processor arguments
            processor_args = {
                'trust_remote_code': trust_remote_code
            }

            # Add num_crops if specified
            if 'num_crops' in processor_settings:
                processor_args['num_crops'] = processor_settings['num_crops']

            self.processor = AutoProcessor.from_pretrained(
                model_id,
                **processor_args
            )

            logger.info("Phi3 processor loaded successfully")
            return self.processor
        except Exception as e:
            logger.error(f"Failed to load Phi3 processor: {e}")
            raise
    
    def _resolve_device(self, device: str) -> str:
        """Apply MPS fallback and resolve device via GPU manager with logging."""
        # Handle MPS disable in config
        mps_conf = self.config.get('mps_fallback', {})
        if mps_conf.get('disable_mps', False) and device.lower() == 'mps':
            logger.info(f"[PHI3-LOADER] MPS disabled in config, falling back to CPU")
            device = 'cpu'
        # Resolve final device
        resolved = get_gpu_manager().resolve_device_spec(device)
        logger.info(f"[PHI3-LOADER] Device resolved: {device} -> {resolved}")
        return resolved

    def _get_transformers(self):
        """Lazy import and return transformer model, processor, and config classes."""
        return _lazy_import_transformers()

    def _build_loading_args(self, model_settings: Dict[str, Any], device: str, trust_remote_code: bool) -> Dict[str, Any]:
        """Build model loading arguments based on device and configuration."""
        device_str = str(device).lower()
        # Parse device-specific config for low_cpu_mem_usage
        low_cpu_mem_usage_config = model_settings.get('low_cpu_mem_usage', {})
        if not isinstance(low_cpu_mem_usage_config, dict):
            raise KeyError("'low_cpu_mem_usage' must be a dict keyed by device (cpu, cuda, mps)")
        if device_str not in low_cpu_mem_usage_config:
            raise KeyError(f"Missing 'low_cpu_mem_usage' for device '{device_str}' in config")
        args = {
            'trust_remote_code': trust_remote_code,
            'low_cpu_mem_usage': low_cpu_mem_usage_config[device_str],
        }
        
        # Log GPU information for debugging
        gpu_manager = get_gpu_manager()
        gpu_manager.log_gpu_info()
        
        # Get optimized attention configuration for Phi-3
        attention_config = gpu_manager.get_attention_config("phi3")
        
        # Use architecture-specific attention implementation
        device_str = str(device).lower()
        if device_str.startswith('cuda'):
            attention_impl = attention_config.get("attn_implementation", "eager")
            
            # Force eager for Phi3V models - they don't support SDPA yet
            if attention_impl == 'sdpa':
                attention_impl = 'eager'
                logger.info("🔧 [PHI3V] Forcing eager attention - Phi3V doesn't support SDPA")
            
            args['attn_implementation'] = attention_impl
            logger.info(f"🎯 [PHI3] Using attention implementation: {attention_impl}")
        else:
            # Force eager for CPU/MPS
            args['attn_implementation'] = 'eager'
            logger.info(f"🔧 [PHI3] Using eager attention for device: {device_str}")
        
        # Fallback to attention manager if architecture detection fails
        try:
            if args.get('attn_implementation') == 'auto':
                attention_manager = get_attention_manager()
                args = attention_manager.configure_model_args(args, device_str)
                logger.info(f"Applied fallback attention optimizations for {device_str}")
        except Exception as e:
            logger.warning(f"Failed to apply attention optimizations: {e}")
            # Final fallback
            args['attn_implementation'] = 'eager'
        
        # Handle torch dtype based on device (strict config discipline, only from model_settings)
        torch_dtype_config = model_settings.get('torch_dtype', {})
        if not isinstance(torch_dtype_config, dict):
            raise KeyError("'torch_dtype' must be a dict keyed by device (cpu, cuda, mps)")
        if device_str not in torch_dtype_config:
            raise KeyError(f"Missing 'torch_dtype' for device '{device_str}' in config")
        dtype_str = torch_dtype_config[device_str]
        if dtype_str == 'auto':
            args['torch_dtype'] = 'auto'  # Let transformers handle it
        else:
            torch = _lazy_import_torch()
            if dtype_str == 'float16':
                args['torch_dtype'] = torch.float16
            elif dtype_str == 'bfloat16':
                args['torch_dtype'] = torch.bfloat16
            elif dtype_str == 'float32':
                args['torch_dtype'] = torch.float32
            else:
                raise ValueError(f"Unsupported torch_dtype '{dtype_str}' for device '{device_str}'")
        
        # Handle device map - avoid device_map for MPS and CPU
        device_map = model_settings.get('device_map')
        if device_map and device_map != 'null' and device_str not in ['mps', 'cpu']:
            # Add explicit memory limits for multi-model scenarios
            if device_str.startswith('cuda'):
                # Get memory allocation from Phi-3 specific configuration
                gpu_manager = get_gpu_manager()
                device_info = gpu_manager.get_device_info()
                if device_info.gpu_info and device_info.gpu_info.memory_gb:
                    # Get Phi-3 memory fraction from caption_generator config
                    config_service = ConfigService()
                    caption_config = config_service.get_section('caption_generator')
                    memory_config = caption_config.get('config', {}).get('memory_allocation', {})
                    gpu_fractions = memory_config.get('gpu_memory_fractions', {})
                    
                    # Determine GPU architecture
                    major, minor = device_info.gpu_info.compute_capability
                    gpu_arch = f"{major + (minor / 10.0):.1f}"
                    
                    # Get memory fraction for this GPU architecture
                    phi3_memory_fraction = gpu_fractions.get(gpu_arch, gpu_fractions.get('default', 0.7))
                    
                    max_memory_gb = device_info.gpu_info.memory_gb * phi3_memory_fraction
                    args['max_memory'] = {0: f"{max_memory_gb:.1f}GB"}
                    logger.info(f"🔧 [PHI3] Allocated {max_memory_gb:.1f}GB GPU memory ({phi3_memory_fraction*100:.0f}% of {device_info.gpu_info.memory_gb:.1f}GB) for arch {gpu_arch}")
            args['device_map'] = device_map
        
        # Handle quantization - only for CUDA
        if hasattr(self, 'config') and 'quantization' in self.config:
            quantization = self.config.get('quantization', {})
            if quantization.get('enabled', False) and device_str.startswith('cuda'):
                quant_config = quantization.get('config', {})
                if quant_config.get('load_in_4bit', False):
                    args['load_in_4bit'] = True
                
        logger.info(f"🔧 [PHI3] Model loading args: {args}")
        return args

    def _handle_device_placement(self, model, device: str):
        device_str = str(device).lower()
        """Handle device placement for different device types."""
        if device_str == 'mps':
            logger.info("Moving model to MPS device...")
            model = model.to('mps')
        elif device_str.startswith('cuda'):
            logger.info("Model loaded on CUDA")
        elif device_str == 'cpu':
            logger.info("Moving model to CPU...")
            model = model.to('cpu')
        else:
            logger.info(f"Model loaded on unknown device: {device_str}")
        
        # Apply attention runtime optimizations
        try:
            attention_manager = get_attention_manager()
            model = attention_manager.optimize_model(model, device_str)
            logger.info(f"Applied attention runtime optimizations for {device_str}")
        except Exception as e:
            logger.warning(f"Failed to apply attention runtime optimizations: {e}")
        
        # Log device information
        if hasattr(model, 'hf_device_map'):
            logger.info(f"Model device map: {model.hf_device_map}")
        else:
            try:
                device_info = next(model.parameters()).device
                logger.info(f"Model loaded on device: {device_info}")
            except StopIteration:
                logger.warning("Could not determine model device")
        
        return model

    def load_pipeline(self):
        """Build and return an ImageToTextPipeline for the Phi-3 model."""
        # Ensure model and processor are loaded
        if self.model is None:
            self.load_model(self.model_id)
        if self.processor is None:
            self.processor = self.load_processor(self.model_id)

        from transformers.pipelines import ImageToTextPipeline
        # Determine device index: use GPU (0) or CPU (-1)
        device_str = str(self.device).lower()
        from shared.utils.device_utils import get_available_device
        # Map 'cpu'->-1 else use GPU index 0
        device = -1 if device_str.startswith('cpu') else 0

        # Choose the correct feature extractor attribute for the processor
        feat_ext = getattr(self.processor, 'feature_extractor', None)
        if feat_ext is None:
            feat_ext = getattr(self.processor, 'image_processor', None)
        if feat_ext is None:
            raise AttributeError("Processor has no attribute 'feature_extractor' or 'image_processor'.")

        # If model was loaded via accelerate (has hf_device_map), pipeline cannot accept device arg
        if hasattr(self.model, 'hf_device_map'):
            return ImageToTextPipeline(
                model=self.model,
                feature_extractor=feat_ext,
                tokenizer=self.processor.tokenizer
            )
        else:
            return ImageToTextPipeline(
                model=self.model,
                feature_extractor=feat_ext,
                tokenizer=self.processor.tokenizer,
                device=device
            )