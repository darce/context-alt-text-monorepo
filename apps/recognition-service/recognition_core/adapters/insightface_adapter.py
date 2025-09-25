"""
InsightFace Adapter

Simplified adapter that wraps the InsightFace model for detection and embedding extraction.
No CVLFace, AdaFace, or quality scoring - just pure InsightFace.
"""

import logging
import time
import os
from typing import Any, Dict, List, Optional
from pathlib import Path
import anyio
import numpy as np
from PIL import Image
import cv2

from recognition_core.domain.interfaces import (
    FaceDetectorPort,
    FaceEmbedderPort,
    RecognitionModelPort,
)
from recognition_core.domain.entities import FaceDetection, FaceEmbedding
from recognition_core.config import get_settings
from shared.infrastructure.gpu_manager import GPUManager

logger = logging.getLogger(__name__)


class InsightFaceAdapter(RecognitionModelPort, FaceDetectorPort, FaceEmbedderPort):
    """
    Single adapter that handles both face detection and embedding extraction
    using InsightFace pipeline.
    """
    
    def __init__(self):
        self.settings = get_settings()
        self.gpu_manager = GPUManager()
        self._app = None
        self._model_loaded = False
        
    async def _ensure_model_loaded(self):
        """Lazy load the InsightFace model."""
        if self._model_loaded:
            return
            
        try:
            import insightface
            
            # Create our cache directory structure (non-hidden)
            cache_dir = Path(self.settings.insightface.cache_dir)
            insightface_cache = cache_dir / "insightface"  # Use non-hidden directory
            insightface_cache.mkdir(parents=True, exist_ok=True)
            
            logger.info(f"📁 Using InsightFace cache directory: {insightface_cache}")
            
            # Get providers using GPU manager
            providers = self._get_providers()
            logger.info(f"🔧 Selected providers for InsightFace: {providers}")
            
            # Set global ONNX providers before creating InsightFace app
            # This is critical because InsightFace sometimes ignores the providers parameter
            try:
                import onnxruntime as ort
                ort.set_default_logger_severity(3)  # Reduce ONNX logging
                
                # Get current available providers
                current_providers = ort.get_available_providers()
                logger.info(f"🔧 ONNX available providers: {current_providers}")
                
                # Filter providers to only use available ones
                filtered_providers = [p for p in providers if p in current_providers]
                if filtered_providers:
                    logger.info(f"🎯 Using filtered providers: {filtered_providers}")
                    providers = filtered_providers
                    
                    # Set global default providers - this ensures InsightFace uses them
                    try:
                        # This is the key fix - set global session options
                        ort.set_default_logger_severity(3)
                        
                        # Create session options with our providers
                        sess_options = ort.SessionOptions()
                        sess_options.log_severity_level = 3
                        
                        # Try to influence global provider selection
                        logger.info(f"🎯 Setting global ONNX provider preference: {providers}")
                        
                        # Environment variables for different providers
                        if "CUDAExecutionProvider" in providers:
                            os.environ["OMP_NUM_THREADS"] = "1"  # Optimize for CUDA
                            os.environ["CUDA_VISIBLE_DEVICES"] = "0"  # Use first GPU
                            logger.info(f"🔥 Set CUDA environment variables")
                        elif "CoreMLExecutionProvider" in providers:
                            os.environ["ONNX_EP_COREML_ENABLED"] = "1"
                            os.environ["ONNX_EP_COREML_USE_CPU_ONLY"] = "0"  # Use GPU acceleration
                            logger.info(f"🚀 Set CoreML environment variables for MPS acceleration")
                            
                    except Exception as e:
                        logger.warning(f"⚠️ Could not set global ONNX options: {e}")
                        
                else:
                    logger.warning(f"⚠️ None of the requested providers {providers} are available in {current_providers}")
                    providers = ["CPUExecutionProvider"]
                    
            except Exception as e:
                logger.warning(f"⚠️ Could not configure ONNX providers: {e}")
            
            # Initialize InsightFace app with explicit providers
            logger.info(f"� Initializing InsightFace with providers: {providers}")
            
            self._app = insightface.app.FaceAnalysis(
                name=self.settings.insightface.model_name,
                root=str(insightface_cache),  # Use our non-hidden cache directory
                providers=providers  # Explicitly pass providers
            )
            
            # Log what providers were actually applied
            if hasattr(self._app, 'models'):
                for model_name, model in self._app.models.items():
                    if hasattr(model, 'session') and hasattr(model.session, 'get_providers'):
                        actual_providers = model.session.get_providers()
                        logger.info(f"🎯 Model {model_name} using providers: {actual_providers}")
                    else:
                        logger.info(f"⚠️ Model {model_name} provider info not available")
            
            # Prepare the model with a dummy context
            self._app.prepare(ctx_id=0, det_size=(640, 640))
            
            self._model_loaded = True
            logger.info(f"✅ InsightFace model loaded: {self.settings.insightface.model_name}")
            logger.info(f"📁 Models stored in: {insightface_cache}")
            
        except Exception as e:
            logger.error(f"❌ Failed to load InsightFace model: {e}")
            raise RuntimeError(f"Failed to initialize InsightFace: {e}")
    
    def _get_providers(self) -> List[str]:
        """Get appropriate execution providers based on GPU manager device detection."""
        # Get available ONNX providers first (optional check)
        available_providers = ["CPUExecutionProvider"]  # Default fallback
        try:
            import onnxruntime as ort
            available_providers = ort.get_available_providers()
            logger.info(f"🔧 Available ONNX providers: {available_providers}")
        except ImportError:
            logger.warning(f"⚠️ onnxruntime not available for provider checking")
        except Exception as e:
            logger.warning(f"⚠️ Could not check ONNX providers: {e}")
        
        # Use GPU manager to detect the best device
        device_info = self.gpu_manager.get_device_info()
        best_device = device_info.best_device
        
        logger.info(f"🔧 GPU Manager detected best device: {best_device}")
        if device_info.cuda_available:
            logger.info(f"🔥 CUDA available with {device_info.device_count} device(s)")
        if device_info.mps_available:
            logger.info(f"🚀 MPS available on macOS")
        
        # Map device to ONNX execution providers based on availability
        if best_device == "cuda" and "CUDAExecutionProvider" in available_providers:
            providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
            logger.info(f"🎯 Selected CUDA providers for best performance")
        elif best_device == "mps" and "CoreMLExecutionProvider" in available_providers:
            # CoreML can leverage Metal/MPS on Apple Silicon
            providers = ["CoreMLExecutionProvider", "CPUExecutionProvider"]
            logger.info(f"🎯 Selected CoreML providers for MPS acceleration")
        else:
            providers = ["CPUExecutionProvider"]
            logger.info(f"🎯 Falling back to CPU providers (best_device: {best_device}, available: {available_providers})")
        
        # Allow configuration override if specified (only if not empty)
        if self.settings.insightface.providers and len(self.settings.insightface.providers) > 0:
            # Only override if providers are explicitly configured (not empty list)
            if self.settings.insightface.providers != [""]:  # Check for empty string too
                providers = self.settings.insightface.providers
                logger.info(f"🔧 Using provider override from config: {providers}")
            else:
                logger.info(f"🔧 Config has empty providers, using auto-detected: {providers}")
        else:
            logger.info(f"🔧 Config providers empty or unset, using auto-detected: {providers}")
        
        logger.info(f"🎯 Final ONNX execution providers: {providers}")
        return providers
    
    def _pil_to_cv2(self, pil_image: Image.Image) -> np.ndarray:
        """Convert PIL Image to OpenCV format."""
        # Convert to RGB if not already
        if pil_image.mode != 'RGB':
            pil_image = pil_image.convert('RGB')
        
        # Convert PIL to numpy array
        img_array = np.array(pil_image)
        
        # Convert RGB to BGR for OpenCV
        cv2_image = cv2.cvtColor(img_array, cv2.COLOR_RGB2BGR)
        
        return cv2_image
    
    async def detect_faces(self, image: Image.Image) -> List[FaceDetection]:
        """Detect faces using InsightFace."""
        await self._ensure_model_loaded()
        
        try:
            # Convert PIL to OpenCV format
            cv2_image = self._pil_to_cv2(image)
            
            # Run face analysis
            faces = self._app.get(cv2_image)
            
            detections = []
            for face in faces:
                # Extract bounding box
                bbox = face.bbox.astype(int)
                x_min, y_min, x_max, y_max = bbox
                
                # Extract confidence (detection score)
                confidence = float(face.det_score)
                
                # Extract landmarks if available
                landmarks = face.kps if hasattr(face, 'kps') else None
                
                detection = FaceDetection(
                    bbox=(x_min, y_min, x_max, y_max),
                    confidence=confidence,
                    landmarks=landmarks
                )
                
                detections.append(detection)
            
            logger.info(f"🔍 Detected {len(detections)} faces")
            return detections
            
        except Exception as e:
            logger.error(f"❌ Face detection failed: {e}")
            return []
    
    async def extract_embeddings(
        self, 
        image: Image.Image, 
        detections: List[FaceDetection]
    ) -> List[FaceEmbedding]:
        """Extract embeddings for detected faces."""
        await self._ensure_model_loaded()
        
        try:
            # Convert PIL to OpenCV format
            cv2_image = self._pil_to_cv2(image)
            
            # Run face analysis to get embeddings
            faces = self._app.get(cv2_image)
            
            embeddings = []
            
            # Match detections with InsightFace results
            for i, detection in enumerate(detections):
                if i < len(faces):
                    face = faces[i]
                    
                    # Extract normalized embedding
                    embedding_vector = face.normed_embedding
                    
                    # Create embedding object
                    embedding = FaceEmbedding(
                        embedding=embedding_vector,
                        detection=detection
                    )
                    
                    embeddings.append(embedding)
            
            logger.info(f"🧠 Extracted {len(embeddings)} embeddings")
            return embeddings
            
        except Exception as e:
            logger.error(f"❌ Embedding extraction failed: {e}")
            return []
    
    async def analyze(self, image: Image.Image) -> List[FaceEmbedding]:
        """
        Combined detection and embedding extraction in a single call.
        More efficient than separate calls.
        """
        await self._ensure_model_loaded()

        def _analyze_sync(pil_image: Image.Image) -> List[FaceEmbedding]:
            try:
                start_time = time.time()
                cv2_image = self._pil_to_cv2(pil_image)
                faces = self._app.get(cv2_image)

                embeddings: List[FaceEmbedding] = []
                for face in faces:
                    bbox = face.bbox.astype(int)
                    x_min, y_min, x_max, y_max = bbox

                    detection = FaceDetection(
                        bbox=(x_min, y_min, x_max, y_max),
                        confidence=float(face.det_score),
                        landmarks=face.kps if hasattr(face, "kps") else None,
                    )

                    embeddings.append(
                        FaceEmbedding(
                            embedding=face.normed_embedding,
                            detection=detection,
                        )
                    )

                processing_time = (time.time() - start_time) * 1000
                logger.info(
                    "🔬 Analyzed image: %s faces in %.1fms",
                    len(embeddings),
                    processing_time,
                )
                return embeddings
            except Exception as exc:  # pragma: no cover - defensive fallback
                logger.error("❌ Image analysis failed: %s", exc)
                return []

        return await anyio.to_thread.run_sync(_analyze_sync, image)

    async def analyze_image(self, image: Image.Image) -> List[FaceEmbedding]:
        """Backward compatible alias for analyze()."""
        return await self.analyze(image)

    def model_info(self) -> Dict[str, Any]:
        """Expose metadata about the underlying InsightFace model."""
        return {
            "model_name": self.settings.insightface.model_name,
            "device": self.settings.insightface.device,
            "providers": self.settings.insightface.providers,
        }
