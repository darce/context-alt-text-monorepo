import logging
import numpy as np
import onnxruntime as ort
from typing import Any, Dict, Tuple, Optional
from shared.infrastructure.gpu_manager import get_gpu_manager
from shared.utils.device_utils import get_available_device
from recognition_core.utils.face_utils import normalize_vec
import cv2
from pathlib import Path

def _get_providers_and_options(resolved_device: str, config: Dict[str, Any]) -> Tuple[list, list]:
    """Get ONNX providers and options for AdaFace model."""
    settings = (config or {}).get('settings', {})
    force_cuda = settings.get('force_cuda_only', False)
    
    if resolved_device == 'cuda':
        providers = ['CUDAExecutionProvider'] if force_cuda else ['CUDAExecutionProvider', 'CPUExecutionProvider']
    else:
        providers = ['CPUExecutionProvider']
    
    # Build provider options
    provider_options = []
    gpu_mem_limit = settings.get('onnx_gpu_mem_limit')
    
    for provider in providers:
        if provider == 'CUDAExecutionProvider' and resolved_device == 'cuda' and gpu_mem_limit:
            provider_options.append({'gpu_mem_limit': gpu_mem_limit})
        else:
            provider_options.append({})
    
    return providers, provider_options

def _validate_model_path(model_path: str) -> str:
    """Validate and return the model path."""
    if not model_path:
        raise ValueError("model_path must be specified for AdaFace adapter")
    
    path_obj = Path(model_path)
    if not path_obj.exists():
        raise FileNotFoundError(f"AdaFace model file not found: {model_path}")
    
    if path_obj.suffix.lower() != '.onnx':
        raise ValueError(f"AdaFace model must be an ONNX file (.onnx), got: {path_obj.suffix}")
    
    return str(path_obj.absolute())

class AdaFaceModel:
    """
    AdaFace IR-101-OCC ONNX model wrapper for face recognition_core.
    Provides 512-dimensional face embeddings.
    """
    
    def __init__(self, model_path: str, device: str = "cpu", config: Dict[str, Any] = None):
        self.model_path = _validate_model_path(model_path)
        self.device = device
        self.config = config or {}
        self.session = None
        self.input_name = None
        self.output_name = None
        self.input_shape = None
        
        # Model-specific configuration
        self.input_size = (112, 112)  # Standard AdaFace input size
        self.mean = np.array([0.5, 0.5, 0.5], dtype=np.float32)
        self.std = np.array([0.5, 0.5, 0.5], dtype=np.float32)
        
        logging.info(f"AdaFace model initialized - path: {self.model_path}, device: {device}")
    
    def load(self):
        """Load the AdaFace ONNX model."""
        if self.session is not None:
            return
        
        try:
            resolved_device = get_gpu_manager().resolve_device_spec(self.device)
            providers, provider_options = _get_providers_and_options(resolved_device, self.config)
            
            logging.info(f"Loading AdaFace model with providers: {providers}")
            
            # Create ONNX Runtime session
            self.session = ort.InferenceSession(
                self.model_path,
                providers=providers,
                provider_options=provider_options
            )
            
            # Get input and output metadata
            self.input_name = self.session.get_inputs()[0].name
            self.output_name = self.session.get_outputs()[0].name
            self.input_shape = self.session.get_inputs()[0].shape
            
            logging.info(f"AdaFace model loaded successfully")
            logging.info(f"Input shape: {self.input_shape}, Input name: {self.input_name}")
            logging.info(f"Output name: {self.output_name}")
            
        except Exception as e:
            logging.error(f"Failed to load AdaFace model: {e}")
            raise
    
    def preprocess(self, face_image: np.ndarray) -> np.ndarray:
        """
        Preprocess face image for AdaFace model inference.
        
        Args:
            face_image: Face image as numpy array (H, W, C) in BGR format
            
        Returns:
            Preprocessed image ready for model inference
        """
        # Convert BGR to RGB
        if len(face_image.shape) == 3 and face_image.shape[2] == 3:
            face_image = cv2.cvtColor(face_image, cv2.COLOR_BGR2RGB)
        
        # Resize to model input size
        face_image = cv2.resize(face_image, self.input_size)
        
        # Normalize to [0, 1]
        face_image = face_image.astype(np.float32) / 255.0
        
        # Apply mean and std normalization
        face_image = (face_image - self.mean) / self.std
        
        # Add batch dimension and transpose to (N, C, H, W)
        face_image = np.transpose(face_image, (2, 0, 1))
        face_image = np.expand_dims(face_image, axis=0)
        
        return face_image
    
    def extract_embedding(self, face_image: np.ndarray) -> np.ndarray:
        """
        Extract 512-dimensional embedding from face image.
        
        Args:
            face_image: Face image as numpy array (H, W, C) in BGR format
            
        Returns:
            512-dimensional face embedding
        """
        if self.session is None:
            raise RuntimeError("AdaFace model not loaded. Call load() first.")
        
        # Preprocess image
        input_tensor = self.preprocess(face_image)
        
        # Run inference
        outputs = self.session.run([self.output_name], {self.input_name: input_tensor})
        embedding = outputs[0][0]  # Remove batch dimension
        
        # Normalize embedding using face_utils helper
        embedding = normalize_vec(embedding)
        
        return embedding
    
    def is_ready(self) -> bool:
        """Check if the model is loaded and ready for inference."""
        return self.session is not None

def load_adaface_model(model_path: str, device: str = None, config: Dict[str, Any] = None) -> AdaFaceModel:
    """
    Load AdaFace IR-101-OCC model for face recognition_core.
    
    Args:
        model_path: Path to the AdaFace ONNX model file
        device: Device to run the model on ("cpu", "cuda", "auto")
        config: Configuration dictionary
        
    Returns:
        Loaded AdaFaceModel instance
    """
    if device is None:
        device = get_available_device()
    
    model = AdaFaceModel(model_path, device, config)
    model.load()
    
    return model
