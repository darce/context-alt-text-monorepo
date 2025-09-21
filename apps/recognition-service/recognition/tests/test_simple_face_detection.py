"""
Simple Face Detection Test

A minimal test to verify the recognition service works with a single image.
"""

import pytest
import time
import os
import warnings
from pathlib import Path
from PIL import Image

# Suppress known third-party warnings
warnings.filterwarnings("ignore", ".*rcond.*", FutureWarning)

# Configure environment before importing RecognitionService
os.environ.setdefault("INSIGHTFACE_CACHE_DIR", "/Volumes/Butter/")
os.environ.setdefault("CACHE_DIR", "/Volumes/Butter/")
os.environ.setdefault("RECOG_INSIGHTFACE_DEVICE", "mps")  # Force MPS for better performance

from recognition.services import RecognitionService


@pytest.fixture
def recognition_service():
    """Create recognition service instance with verified cache configuration."""
    # Verify cache environment is properly set
    cache_dir = os.getenv("INSIGHTFACE_CACHE_DIR", "/tmp/insightface_models")
    print(f"🔧 Using InsightFace cache directory: {cache_dir}")
    
    # Check if models already exist to avoid re-download
    expected_cache = Path(cache_dir) / "insightface" / "models" / "buffalo_l"
    if expected_cache.exists():
        print(f"✅ Found existing models in cache: {expected_cache}")
        print(f"📁 Model files: {list(expected_cache.glob('*.onnx'))}")
    else:
        print(f"⚠️  Models not found in cache, will be downloaded: {expected_cache}")
    
    # Show GPU/device information
    try:
        from shared.infrastructure.gpu_manager import GPUManager
        gpu_manager = GPUManager()
        device_info = gpu_manager.get_device_info()
        print(f"🖥️  Best device detected: {device_info.best_device}")
        print(f"🔥 CUDA available: {device_info.cuda_available}")
        print(f"🚀 MPS available: {device_info.mps_available}")
        if device_info.gpu_info:
            print(f"🎯 GPU: {device_info.gpu_info.name} ({device_info.gpu_info.memory_gb:.1f}GB)")
    except Exception as e:
        print(f"⚠️  Could not get device info: {e}")
    
    return RecognitionService()


@pytest.fixture
def project_root():
    """Get project root path."""
    return Path(__file__).parent.parent.parent


@pytest.fixture
def mock_images_path(project_root):
    """Get path to mock images."""
    mock_path = project_root / "scripts" / "mock_images"
    if not mock_path.exists():
        pytest.skip("Mock images not found")
    return mock_path


@pytest.mark.asyncio
async def test_single_image_face_detection(recognition_service, mock_images_path):
    """
    Test face detection on a single image to verify the pipeline works.
    """
    # Use a simple image that should have a face
    test_image = "liam-maloney-home.jpg"
    image_path = mock_images_path / test_image
    
    if not image_path.exists():
        pytest.skip(f"Test image not found: {image_path}")
    
    print(f"Testing face detection on: {test_image}")
    
    try:
        # Load and process image
        image = Image.open(image_path)
        print(f"Image loaded: {image.size}")
        
        start_time = time.time()
        result = await recognition_service.recognize_faces(image)
        processing_time = (time.time() - start_time) * 1000
        
        # Check results
        num_faces_detected = len(result.face_detections)
        print(f"Faces detected: {num_faces_detected}")
        print(f"Processing time: {processing_time:.1f}ms")
        
        # Check if we have face detections
        if num_faces_detected > 0:
            for i, detection in enumerate(result.face_detections):
                x_min, y_min, x_max, y_max = detection.bbox
                print(f"Face {i+1}: bbox=({x_min:.0f}, {y_min:.0f}, {x_max:.0f}, {y_max:.0f})")
                print(f"  Confidence: {detection.confidence:.3f}")
                
                if detection.landmarks is not None:
                    print(f"  Landmarks: {len(detection.landmarks)} points")
        
        # Check if we have embeddings  
        if len(result.face_embeddings) > 0:
            for i, face_embedding in enumerate(result.face_embeddings):
                print(f"Face {i+1} embedding: {len(face_embedding.embedding)} dimensions")
        
        # Check if we have matches
        if len(result.matches) > 0:
            for i, match in enumerate(result.matches):
                print(f"Match {i+1}: {match.entry.name} (similarity: {match.similarity:.3f})")
        
        # Basic assertions
        assert num_faces_detected > 0, "Should detect at least one face"
        # Note: Processing time is measured for informational purposes only
        print(f"ℹ️  Processing time: {processing_time:.1f}ms (includes model loading on first run)")
        
        print("✅ Single image face detection test passed")
        
    except Exception as e:
        print(f"❌ Error during face detection: {e}")
        raise


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
