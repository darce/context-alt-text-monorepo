import logging
import numpy as np
from typing import Any, Dict, Tuple
from shared.infrastructure.gpu_manager import get_gpu_manager
from shared.utils.device_utils import get_available_device
from recognition.utils.face_utils import to_rgb_array, cosine_similarity

# Private helpers for loader
def _get_detection_size(config: Dict[str, Any]) -> int:
    settings = (config or {}).get('settings', {})
    det_size = settings.get('det_size')
    if det_size is None:
        raise ValueError("det_size must be set in config['settings'] for InsightFace loader.")
    return det_size

def _get_providers_and_ctx(resolved_device: str, config: Dict[str, Any]) -> Tuple[list, int]:
    settings = (config or {}).get('settings', {})
    force_cuda = settings.get('force_cuda_only', False)
    if resolved_device == 'cuda':
        providers = ['CUDAExecutionProvider'] if force_cuda else ['CUDAExecutionProvider', 'CPUExecutionProvider']
        ctx_id = 0
    else:
        providers = ['CPUExecutionProvider']
        ctx_id = -1
    return providers, ctx_id

def load_insightface_model(model_path: str, device: str = None, config: Dict[str, Any] = None) -> Any:
    """
    Loads an InsightFace model with face detection and recognition capabilities.
    All config must be passed in from settings.py via the factory.
    Dynamically sets ONNX providers based on device.
    """
    if device is None:
        device = get_available_device()
        
    logging.info(f"🔄 Loading InsightFace model: {model_path} on device: {device}")
        
    try:
        import insightface
        logging.info("✅ InsightFace library imported successfully")
        
        # Resolve detection size and ONNX providers
        resolved_device = get_gpu_manager().resolve_device_spec(device)
        logging.info(f"📱 Resolved device: {resolved_device}")
        
        det_size = _get_detection_size(config)
        logging.info(f"🔍 Detection size: {det_size}")
        
        providers, ctx_id = _get_providers_and_ctx(resolved_device, config)
        logging.info(f"⚙️ ONNX providers: {providers}, ctx_id: {ctx_id}")
        
        # Build provider_options list matching providers order for ONNXRuntime
        settings = (config or {}).get('settings', {})
        gpu_mem_limit = settings.get('onnx_gpu_mem_limit')  # bytes
        logging.info(f"💾 GPU memory limit: {gpu_mem_limit}")
        
        provider_options_list = []
        for prov in providers:
            if prov == 'CUDAExecutionProvider' and resolved_device == 'cuda' and gpu_mem_limit:
                provider_options_list.append({'gpu_mem_limit': gpu_mem_limit})
            else:
                provider_options_list.append({})
        logging.info(f"⚙️ Provider options: {provider_options_list}")
        
        # Initialize FaceAnalysis with explicit model name, providers, and provider options list
        logging.info(f"🏗️ Creating FaceAnalysis instance...")
        app = insightface.app.FaceAnalysis(
            name=model_path,
            providers=providers,
            provider_options=provider_options_list,
        )
        logging.info(f"✅ FaceAnalysis instance created")
        
        logging.info(f"🔧 Preparing model with ctx_id={ctx_id}, det_size=({det_size}, {det_size})")
        app.prepare(ctx_id=ctx_id, det_size=(det_size, det_size))
        logging.info(f"✅ InsightFace model prepared successfully")
        
        logging.info(f"[INSIGHTFACE-LOADER] Loaded InsightFace app with device: {resolved_device}, providers: {providers}")
        
        # Log which models were loaded to debug landmark issue
        logging.info(f"[INSIGHTFACE-LOADER] Available models: {[model.taskname for model in app.models.values()]}")
        
        # Add custom methods for API compatibility
        def get_embedding(img):
            """Extract face embedding from a PIL Image containing a single face."""
            img_array = to_rgb_array(img)
            
            faces = app.get(img_array)
            if not faces:
                return None
            
            # Return embedding of the first face
            return faces[0].embedding
        
        def compare_embeddings(e1, e2):
            """Compute cosine similarity between two face embeddings."""
            if e1 is None or e2 is None:
                return 0.0
            
            # Ensure embeddings are numpy arrays
            if not isinstance(e1, np.ndarray):
                e1 = np.array(e1)
            if not isinstance(e2, np.ndarray):
                e2 = np.array(e2)
            
            # Compute cosine similarity using face_utils helper
            return float(cosine_similarity(e1, e2, normalize=True))
        
        # Attach methods to the app object
        app.get_embedding = get_embedding
        app.compare_embeddings = compare_embeddings
        
        logging.info("🎉 InsightFace model loaded and configured successfully")
        return app
        
    except ImportError as e:
        logging.error(f"❌ [INSIGHTFACE-LOADER] InsightFace not installed: {e}")
        raise ImportError("InsightFace package is required. Install with: pip install insightface")
    except Exception as e:
        logging.error(f"❌ [INSIGHTFACE-LOADER] Failed to load model: {e}")
        logging.error(f"🔧 Debug info: model_path={model_path}, device={device}, resolved_device={resolved_device if 'resolved_device' in locals() else 'unknown'}")
        raise
