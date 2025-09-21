#!/usr/bin/env python3
"""
Build-time utility for pre-downloading and warming up Hugging Face model files during Docker build.

This utility improves startup performance by downloading Hugging Face model files
to the container cache during build time, and optionally loading them to CPU memory
for faster runtime initialization. No GPU memory allocation during build.

YOLO models are stored locally in shared/infrastructure/models/ and copied during Docker build.

Environment Variables:
    SKIP_MODEL_PRELOAD: Skip all model preloading (default: false)
    PRELOAD_CPU_WARMUP: Enable CPU-only model loading for faster startup (default: true)  
    PRELOAD_FILES_ONLY: Download files only, skip CPU warmup (default: false)
    HF_HOME: Hugging Face cache directory (default: /data/cache/huggingface_cache)

Memory Requirements:
    - Files only: ~2-4GB (download only)
    - CPU warmup: ~8-12GB (temporary model loading)
    - Auto-fallback if insufficient memory detected

Location: /shared/infrastructure (build/infrastructure utility)
Usage: Called via `python3 -m shared.infrastructure.preload_model` in Dockerfile
"""
import os
import logging
import torch
from shared.config.settings import get_config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def warmup_model_cpu_only(model_id: str, cache_dir: str) -> bool:
    """
    Load model to CPU memory during build for faster runtime startup.
    This pre-loads the model weights into CPU memory and then releases them,
    ensuring the model is cached and validated.
    """
    try:
        from transformers import AutoModelForCausalLM, AutoProcessor
        
        logger.info(f"🔥 CPU-only warmup for model: {model_id}")
        
        # Download and load processor first
        processor = AutoProcessor.from_pretrained(
            model_id,
            trust_remote_code=True,
            cache_dir=cache_dir
        )
        logger.info("✅ Processor loaded successfully")
        
        # Load model to CPU only (no GPU memory during build)
        model = AutoModelForCausalLM.from_pretrained(
            model_id,
            device_map="cpu",  # Force CPU during build
            torch_dtype=torch.bfloat16,
            trust_remote_code=True,
            _attn_implementation="eager",  # Most compatible attention
            cache_dir=cache_dir,
            low_cpu_mem_usage=True  # Reduce memory usage during loading
        )
        logger.info("✅ Model loaded to CPU successfully")
        
        # Cleanup to free memory immediately
        del model, processor
        
        # Clear any cached tensors
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        
        logger.info(f"🎉 CPU warmup completed for: {model_id}")
        return True
        
    except Exception as e:
        logger.error(f"❌ CPU warmup failed for {model_id}: {e}")
        return False


def download_model_files():
    """Download model files and optionally perform CPU-only warmup during Docker build"""
    
    # Check if we should skip download during build
    skip_preload = os.getenv('SKIP_MODEL_PRELOAD', '').lower() in ('true', '1', 'yes')
    if skip_preload:
        logger.info("⏭️ Model preloading skipped (SKIP_MODEL_PRELOAD=true)")
        return True
    
    # Check what type of preload to perform
    cpu_warmup = os.getenv('PRELOAD_CPU_WARMUP', 'true').lower() in ('true', '1', 'yes')
    files_only = os.getenv('PRELOAD_FILES_ONLY', 'false').lower() in ('true', '1', 'yes')
    
    # Check available memory (basic check)
    memory_threshold = 8  # GB
    if cpu_warmup:
        memory_threshold = 12  # Higher threshold for CPU warmup
        
    try:
        import psutil
        available_memory_gb = psutil.virtual_memory().available / (1024**3)
        if available_memory_gb < memory_threshold:
            logger.warning(f"⚠️ Low memory ({available_memory_gb:.1f}GB < {memory_threshold}GB)")
            if cpu_warmup:
                logger.info("🔄 Falling back to files-only download due to low memory")
                files_only = True
                cpu_warmup = False
            else:
                logger.warning("⏭️ Skipping preload due to low memory")
                return True
    except ImportError:
        # psutil not available, continue cautiously
        logger.info("Memory check unavailable, proceeding with caution")
        if cpu_warmup:
            logger.info("🔄 Falling back to files-only due to missing memory info")
            files_only = True
            cpu_warmup = False
    
    try:
        cfg = get_config()
        
        # Download YOLO models first (fast, reliable)
        logger.info("📦 Downloading YOLO models...")
        yolo_success = download_yolo_models(cfg.get('adapters', {}))
        if not yolo_success:
            logger.warning("⚠️ YOLO model download failed, but continuing with HuggingFace models")
        
        # Use the original working path structure for adapters config
        caption_config = cfg.get("caption_generator", {}).get("config", {})
        model_id = caption_config.get("model_id", "microsoft/Phi-3.5-vision-instruct")
        
        # Only preload if it's not a mock
        caption_type = cfg.get("caption_generator", {}).get("type", "mock")
        if caption_type == "mock":
            logger.info("⏭️ Caption generator is mock type, skipping HuggingFace model download")
            return yolo_success  # Return YOLO success status
        
        cache_dir = os.environ.get('HF_HOME', '/data/cache/huggingface_cache')
        
        logger.info(f"Pre-downloading HuggingFace model files for: {model_id}")
        logger.info(f"Mode: {'CPU warmup' if cpu_warmup else 'Files only'}")
        
        # Always download model files first
        from huggingface_hub import snapshot_download
        
        # Download model files to cache with minimal memory usage
        snapshot_download(
            repo_id=model_id,
            cache_dir=cache_dir,
            local_files_only=False,
            resume_download=True,
            # Only download essential files to save space and memory
            ignore_patterns=[
                "*.msgpack", 
                "*.safetensors.index.json",
                "*.bin",  # Skip pytorch bins, use safetensors
                "pytorch_model*.bin"
            ]
        )
        
        logger.info(f"✅ HuggingFace model files cached successfully: {model_id}")
        
        # Perform CPU warmup if requested and memory allows
        if cpu_warmup and not files_only:
            logger.info("🔥 Starting CPU-only model warmup...")
            warmup_success = warmup_model_cpu_only(model_id, cache_dir)
            if not warmup_success:
                logger.warning("⚠️ CPU warmup failed, but files are cached")
                # Don't fail the build - files are still cached
        
        return True
        
    except Exception as e:
        # Don't fail the build if download fails - runtime will handle it
        logger.warning(f"⚠️ Model download failed (runtime will retry): {e}")
        return False

def download_yolo_models(config: dict) -> bool:
    """
    Download YOLO models during Docker build to shared/infrastructure/models/.
    Skip if model already exists (e.g., from Git LFS).
    """
    try:
        models_to_check = []
        
        # Check object detector YOLO model
        object_detector = config.get("object_detector", {})
        if object_detector.get("type") == "yolo":
            model_path = object_detector.get("config", {}).get("model_path")
            if model_path and model_path.endswith('.pt'):
                models_to_check.append(("Object Detection", model_path))
        
        if not models_to_check:
            logger.info("ℹ️ No YOLO models found in configuration")
            return True
        
        # Check if models already exist (from Git LFS)
        all_models_exist = True
        for model_type, model_path in models_to_check:
            if os.path.exists(model_path):
                file_size = os.path.getsize(model_path) / (1024*1024)  # MB
                logger.info(f"✅ {model_type} YOLO model already exists: {model_path} ({file_size:.1f}MB)")
            else:
                all_models_exist = False
                logger.info(f"❌ {model_type} YOLO model missing: {model_path}")
        
        if all_models_exist:
            logger.info("✅ All YOLO models already available (Git LFS), skipping download")
            return True
        
        # If we get here, we need to download missing models
        logger.info("🔽 Some YOLO models missing, attempting download...")
        
        from ultralytics import YOLO
        
        # Ensure models directory exists
        models_dir = "shared/infrastructure/models"
        os.makedirs(models_dir, exist_ok=True)
        
        # Convert to download format
        models_to_download = []
        for model_type, model_path in models_to_check:
            if not os.path.exists(model_path):
                model_name = os.path.basename(model_path)
                models_to_download.append((model_type, model_name, model_path))
        
        # Download each missing YOLO model
        for model_type, model_name, target_path in models_to_download:
            target_file = target_path  # Use the full path directly
            
            logger.info(f"🔽 Downloading {model_type} YOLO model: {model_name}")
            
            # Set YOLO to non-verbose mode during download
            os.environ['YOLO_VERBOSE'] = 'false'
            
            try:
                # Download the model (this will cache it in ~/.ultralytics/)
                model = YOLO(model_name, verbose=False)
                logger.info(f"✅ Downloaded {model_type} YOLO model: {model_name}")
                
                # Find where ultralytics cached the model and copy it to our models directory
                import shutil
                
                # Ultralytics can save models in multiple locations, check them all
                possible_locations = [
                    # Current working directory (where the script runs)
                    os.path.join(os.getcwd(), model_name),
                    # User's ultralytics cache directory
                    os.path.join(os.path.expanduser("~"), ".ultralytics", model_name),
                    # Alternative cache locations
                    os.path.join("/tmp", model_name),
                    model_name,  # Sometimes it's just in the current directory
                ]
                
                # Find the downloaded model
                source_path = None
                for location in possible_locations:
                    if os.path.exists(location):
                        source_path = location
                        logger.info(f"📍 Found model at: {location}")
                        break
                
                if source_path:
                    # Copy to our target location
                    shutil.copy2(source_path, target_file)
                    file_size = os.path.getsize(target_file) / (1024*1024)  # MB
                    logger.info(f"✅ Copied {model_name} to {target_file} ({file_size:.1f}MB)")
                else:
                    logger.warning(f"⚠️ Could not locate downloaded model {model_name}")
                    logger.info(f"🔍 Searched locations: {possible_locations}")
                    # List what files are actually in the working directory for debugging
                    current_files = [f for f in os.listdir('.') if f.endswith('.pt')]
                    if current_files:
                        logger.info(f"📁 Found .pt files in current directory: {current_files}")
                    return False
                
                # Clean up reference
                del model
                
            except Exception as e:
                logger.warning(f"⚠️ Failed to download {model_type} YOLO model {model_name}: {e}")
                return False
        
        logger.info(f"✅ Successfully downloaded and cached {len(models_to_download)} YOLO models")
        return True
        
    except ImportError as e:
        logger.warning(f"⚠️ Ultralytics not available for YOLO download: {e}")
        return False
    except Exception as e:
        logger.warning(f"⚠️ YOLO model download failed: {e}")
        return False

if __name__ == "__main__":
    download_model_files()
