import logging
from PIL import Image
from typing import Optional, Dict, Any, Tuple
from analysis.ports.caption_generation_base import ICaptionGeneration
from shared.infrastructure.attention_optimizers import get_attention_manager
import importlib
import torch
from shared.utils.device_utils import get_available_device

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logger.propagate = True

def is_flash_attn_available():
    return importlib.util.find_spec("flash_attn") is not None

class Phi3CaptionAdapter(ICaptionGeneration):
    def __init__(self, model_id: str, device: str = None, config: Dict[str, Any] = None, **kwargs):
        """Initialize Phi3 caption adapter."""
        if device is None:
            device = get_available_device()
        super().__init__(model_id, device, **kwargs)
        self.config = config or {}
        self.model_loader = None
        self.model = None
        self.processor = None
        
    def initialize(self, **kwargs):
        """Initialize the Phi3 model and processor."""
        if self._initialized:
            logger.info("Phi3 adapter already initialized")
            return
            
        try:
            logger.info(f"Initializing Phi3 adapter with model: {self.model_id}")
            
            # Import model loader
            from shared.infrastructure.model_loaders.phi3_model_loader import Phi3ModelLoader

            # Create model loader with configuration
            self.model_loader = Phi3ModelLoader(
                model_id=self.model_id,
                device=self.device,
                config=self.config
            )
            
            # Load model and processor
            self.model = self.model_loader.load_model(self.model_id, self.device)
            self.processor = self.model_loader.load_processor(self.model_id)
            
            self._initialized = True
            logger.info("Phi3 adapter initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize Phi3 adapter: {e}")
            self._initialized = False
            raise
    
    def is_ready(self) -> bool:
        """Check if the adapter is ready for inference."""
        return (
            self._initialized and 
            self.model is not None and 
            self.processor is not None
        )
    
    def generate_caption(
        self, 
        image: Image.Image, 
        prompt: str = None, 
        **kwargs: Dict[str, Any]
    ) -> str:
        """Generate a caption for the given image using Phi3 Vision."""
        if not self.is_ready():
            raise RuntimeError("Phi3 adapter not initialized. Call initialize() first.")
        
        # Main caption generation flow
        # 1) Build prompt text
        prompt_text = self._build_prompt_text(prompt)
        logger.info(f"Generating caption with prompt: {prompt_text[:100]}...")
        # 2) Prepare inputs and config
        inputs, generation_config = self._prepare_inputs(image, prompt_text, **kwargs)
        # 3) Generate token IDs with MPS/CPU fallback
        generate_ids = self._generate_ids_with_fallback(inputs, generation_config)
        # 4) Decode and return final response
        response = self._decode_response(inputs, generate_ids)
        logger.info(f"Generated caption: {response}")
        return response.strip()
    
    def _get_default_prompt(self) -> str:
        """Get the default prompt from configuration. Raises error if missing."""
        from shared.config.settings import get_config
        
        try:
            config = get_config()
        except Exception as e:
            raise RuntimeError(f"Failed to load configuration: {e}")
        
        caption_config = config.get('caption')
        if not caption_config:
            raise ValueError("Missing 'caption' configuration section in settings.yaml")
        
        prompt_template = caption_config.get('prompt_template')
        if not prompt_template:
            raise ValueError("Missing 'prompt_template' in caption configuration. Please add 'caption.prompt_template' to settings.yaml")
        
        return prompt_template
    
    def _move_inputs_to_device(self, inputs):
        """Move input tensors to the same device as the model."""
        device = next(self.model.parameters()).device
        moved_inputs = {}
        for key, value in inputs.items():
            if torch.is_tensor(value):
                moved_inputs[key] = value.to(device)
            else:
                moved_inputs[key] = value
                
        return moved_inputs
    
    def _get_generation_config(self, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        """Get generation configuration from settings.yaml. Raises error if missing required settings."""
        from shared.config.settings import get_config
        
        try:
            config = get_config()
        except Exception as e:
            raise RuntimeError(f"Failed to load configuration: {e}")
        
        # Get caption generator config from settings
        caption_generator_config = config.get('caption_generator', {})
        if not caption_generator_config:
            raise ValueError("Missing 'caption_generator' configuration section in settings.yaml")
        
        generator_config = caption_generator_config.get('config', {})
        if not generator_config:
            raise ValueError("Missing 'config' section in 'caption_generator' configuration in settings.yaml")
        
        # Get text generation settings from config
        generation_config = generator_config.get('text_generation', {}).copy()
        if not generation_config:
            raise ValueError("Missing 'text_generation' configuration in 'caption_generator.config' section of settings.yaml")
        
        # Validate required generation parameters
        required_params = ['max_new_tokens']
        for param in required_params:
            if param not in generation_config:
                raise ValueError(f"Missing required generation parameter '{param}' in settings.yaml caption_generator.config.text_generation section")
        
        # Override with any kwargs passed to generate_caption
        generation_config.update(kwargs)
        
        # Add tokenizer-specific settings if available - but don't override eos_token_id from generate call
        if self.processor and hasattr(self.processor, 'tokenizer'):
            if 'pad_token_id' not in generation_config:
                # Use eos_token_id as pad_token_id if not set
                pad_token_id = getattr(self.processor.tokenizer, 'pad_token_id', None)
                if pad_token_id is None:
                    pad_token_id = getattr(self.processor.tokenizer, 'eos_token_id', None)
                generation_config['pad_token_id'] = pad_token_id
        
        # Clean up None values and non-generation parameters
        cleaned_config = {}
        for key, value in generation_config.items():
            if value is not None and key not in ['template', 'prompt']:
                cleaned_config[key] = value
        
        logger.debug(f"Generation config: {cleaned_config}")
        return cleaned_config
    
    # --- New helper methods for generate_caption ---
    def _build_prompt_text(self, prompt: Optional[str]) -> str:
        """Ensure prompt and apply chat template."""
        if prompt is None:
            prompt = self._get_default_prompt()
        messages = [{"role": "user", "content": f"<|image_1|>\n{prompt}"}]
        return self.processor.tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )

    def _prepare_inputs(self, image: Image.Image, prompt_text: str, **kwargs) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """Process prompts and images into model inputs and generation parameters."""
        inputs = self.processor(prompt_text, [image], return_tensors="pt")
        inputs = self._move_inputs_to_device(inputs)
        generation_config = self._get_generation_config(kwargs)
        return inputs, generation_config

    def _generate_ids_with_fallback(self, inputs, generation_config):
        """Generate tokens with optional CPU fallback for MPS errors."""
        # Set up attention context if available
        try:
            ctx = get_attention_manager().get_inference_context(self.device)
        except Exception:
            from contextlib import nullcontext
            ctx = nullcontext()
        # Attempt generation
        with torch.no_grad():
            try:
                with ctx:
                    if 'eos_token_id' not in generation_config:
                        generation_config['eos_token_id'] = self.processor.tokenizer.eos_token_id
                    return self.model.generate(
                        **inputs,
                        **generation_config
                    )
            except Exception as e:  # broaden exception for fallback
                # Check for MPS placeholder storage error to fallback to CPU
                if ("MPS" in str(e) and "Placeholder storage" in str(e)):
                    from shared.config.settings import get_config
                    mps_conf = get_config()['caption_generator']['config'].get('mps_fallback', {})
                    if mps_conf.get('enable_cpu_fallback', True):
                        try:
                            orig_dev = next(self.model.parameters()).device
                            self.model = self.model.cpu()
                            inputs_cpu = {k: v.cpu() if hasattr(v, 'cpu') else v for k, v in inputs.items()}
                            if 'eos_token_id' not in generation_config:
                                generation_config['eos_token_id'] = self.processor.tokenizer.eos_token_id
                            ids = self.model.generate(
                                **inputs_cpu,
                                **generation_config
                            )
                            self.model = self.model.to(orig_dev)
                            return ids
                        except Exception as cpu_e:
                            logger.error(f"CPU fallback generation failed: {cpu_e}")
                            raise RuntimeError(f"Caption generation CPU fallback failed: {cpu_e}")
                logger.error(f"Caption generation failed on device {self.device}: {e}")
                raise RuntimeError(f"Caption generation failed: {e}")

    def _decode_response(self, inputs, generate_ids) -> str:
        """Trim prompt tokens and decode the generated tokens to text."""
        input_len = inputs['input_ids'].shape[1]
        if generate_ids.shape[1] > input_len:
            out_ids = generate_ids[:, input_len:]
            return self.processor.batch_decode(
                out_ids, skip_special_tokens=True, clean_up_tokenization_spaces=False
            )[0]
        return ""
