import os
import time
from datetime import datetime
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
import threading
import logging
import json
from pathlib import Path
from typing import Optional
from shared.config.logging_config import setup_logging
from shared.config.settings import get_config
from shared.startup.startup_manager import StartupManager, StartupConfig, get_startup_manager
from shared.enums.startup_phase import StartupPhase
from analysis.services.scene_analysis_service import SceneAnalysisService
from api.routes.main import router as main_router
from api.routes.media import router as media_router
from api.routes.roster import router as roster_router
from api.routes.main import set_scene_analysis_service
from recognition_core.config import get_settings as get_recognition_settings
import asyncio

# Configure cache directories before any model loads
def configure_cache_dirs() -> None:
    """Set cache directories; error if any are missing.

    Resolution order per variable:
    1. Explicit value in settings.yaml (cache.*)
    2. Environment variable already set (including .env)

    If neither source provides a value the service aborts so configuration
    problems surface immediately.
    """

    settings = get_recognition_settings()
    cache = settings.cache

    def resolve(env_var: str, configured: Optional[str]) -> str:
        raw_value = configured or os.environ.get(env_var)
        if not raw_value:
            raise RuntimeError(
                f"Missing cache directory for {env_var}. Configure cache.{env_var.lower()} in settings.yaml "
                "or export the environment variable before launching the service."
            )
        return os.path.expanduser(os.path.expandvars(raw_value))

    targets = {
        "HF_HOME": cache.hf_home,
        "HF_DATASETS_CACHE": cache.hf_datasets_cache,
        "TORCH_HOME": cache.torch_home,
    }

    for env_var, configured in targets.items():
        os.environ[env_var] = resolve(env_var, configured)


configure_cache_dirs()

# Configure logging via our logging_config
setup_logging()
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Global variables for managing shared resources between lifespan and startup
startup_manager = None
scene_composer = None 
scene_analysis_service = None

def _get_warmup_benchmark_results():
    """Get warmup benchmark results for performance reporting."""
    try:
        from shared.utils.warmup_benchmark import get_cached_benchmark_results
        results = get_cached_benchmark_results()
        
        if results and results.get("success"):
            return {
                "available": True,
                "cold_start_time": results.get("cold_start_time", 0),
                "warm_start_time": results.get("warm_start_time", 0),
                "time_saved": results.get("time_saved", 0),
                "percentage_improvement": results.get("percentage_improvement", 0),
                "timestamp": results.get("timestamp", "unknown")
            }
        else:
            return {
                "available": False,
                "reason": "No recent benchmark data available"
            }
    except Exception as e:
        return {
            "available": False,
            "reason": f"Benchmark error: {str(e)}"
        }

# --- Initialization logic ---
def initialize_application(app: FastAPI):
    """Initialize the application using StartupManager, using app.state for state tracking"""
    global startup_manager, scene_composer, scene_analysis_service
    
    # Set initialization state
    app.state.is_initializing = True
    app.state.initialization_complete = False

    # Load startup configuration from settings.yaml
    app_config = get_config()
    # Override for background thread execution in dict config
    if 'startup' in app_config:
        app_config['startup']['background_initialization'] = False

    try:
        # Get or create the global startup manager instance
        startup_config = StartupConfig.from_config(app_config["startup"])
        startup_manager = get_startup_manager(startup_config)
        logger.info("🔧 [STARTUP] Starting initialization process...")
        # Run the initialization process
        scene_composer = startup_manager.initialize()
        # Initialize SceneAnalysisService with the composer and roster service
        from api.dependencies import get_roster_service
        roster_service = get_roster_service()

        scene_analysis_service = SceneAnalysisService(scene_composer, roster_service)
        set_scene_analysis_service(scene_analysis_service)

        # Mark initialization as complete
        app.state.is_initializing = False
        app.state.initialization_complete = True
        # Log final summary
        metrics = startup_manager.get_metrics()
        if metrics.total_time:
            completion_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
            logger.info("🎯 [STARTUP] Application fully initialized in %.2fs at %s", metrics.total_time, completion_time)
            logger.info("📊 [STARTUP] Adapter creation took %.2fs", metrics.adapter_creation_time)
    except Exception as e:
        logger.error("❌ [STARTUP] Application initialization failed: %s", e)
        import traceback
        traceback.print_exc()
        app.state.is_initializing = False
        app.state.initialization_complete = False
        if startup_manager:
            startup_manager.current_phase = StartupPhase.FAILED

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("===== Application Startup at %s =====", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    
    # Start background initialization in a separate thread
    init_thread = threading.Thread(target=initialize_application, args=(app,), daemon=True)
    init_thread.start()
    
    # Wait for background init to complete
    while not getattr(app.state, "initialization_complete", False):
        await asyncio.sleep(0.1)
    
    # Get the caption pipeline from the StartupManager after initialization is complete
    # Load config to get the startup manager (it should already exist from initialize_application)
    app_config = get_config()
    startup_config = StartupConfig.from_config(app_config["startup"])
    startup_manager = get_startup_manager(startup_config)
    app.state.img2text = startup_manager.get_caption_pipeline()
    
    logger.info("🚀 [STARTUP] App ready - background initialization complete.")
    yield
    # Clean up resources
    logger.info("===== Application Shutting Down =====")
    
    # Clean up GPU memory using gpu_core
    try:
        from shared.infrastructure.gpu_manager import get_gpu_manager
        gpu_manager = get_gpu_manager()
        gpu_manager.clear_gpu_memory_cache()
    except Exception as e:
        logger.warning(f"Failed to clear GPU cache via gpu_core: {e}")
    
    # Reset global variables
    scene_composer = None
    startup_manager = None

# --- FastAPI app creation ---
app = FastAPI(lifespan=lifespan)
app.state.initialization_complete = False
app.state.is_initializing = True

# --- Include API routes ---
app.include_router(main_router, prefix="/api/v0")
# Media upload endpoints
app.include_router(media_router, prefix="/api/v0")
# Roster management endpoints
app.include_router(roster_router, prefix="/api/v0")
# Recognition service endpoints
# Legacy recognition routes removed; all endpoints served via api routes.

# --- Middleware ---
ENABLE_REQUEST_TIMING = os.getenv("ENABLE_REQUEST_TIMING", "false").lower() == "true"
if ENABLE_REQUEST_TIMING:
    @app.middleware("http")
    async def add_request_timing(request: Request, call_next):
        start_time = time.time()
        request_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
        
        print(f"🕒 [APP-REQUEST] {request.method} {request.url.path} at: {request_time}")
        
        response = await call_next(request)
        
        process_time = time.time() - start_time
        response_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
        
        print(f"🕒 [APP-RESPONSE] {request.method} {request.url.path} at: {response_time} (took {process_time:.3f}s)")
        
        return response
    
    print("🕒 [STARTUP] Request timing middleware enabled")

# --- Route handlers ---
@app.get("/")
async def root():
    global startup_manager, scene_composer
    
    if startup_manager is None:
        status_message = "Alt Text Captioning API is starting up."
        app_status = "starting"
    elif startup_manager.current_phase == StartupPhase.COMPLETED and scene_composer is not None:
        status_message = "Alt Text Captioning API is ready and fully operational."
        app_status = "ready"
    elif startup_manager.current_phase == StartupPhase.FAILED:
        status_message = "Alt Text Captioning API initialization failed."
        app_status = "error"
    else:
        status_message = "Alt Text Captioning API is starting - models loading in background."
        app_status = "initializing"
    
    return {
        "status": app_status, 
        "message": status_message,
        "initialization_status": {
            "phase": startup_manager.current_phase.value if startup_manager else "unknown",
            "complete": startup_manager.current_phase == StartupPhase.COMPLETED if startup_manager else False,
            "in_progress": startup_manager.current_phase not in [StartupPhase.IDLE, StartupPhase.COMPLETED, StartupPhase.FAILED] if startup_manager else False,
            "scene_composer_ready": scene_composer is not None
        }
    }

@app.get("/ready")
async def ready_check():
    """Readiness probe - returns 200 only when fully initialized"""
    global startup_manager, scene_composer
    
    if startup_manager and startup_manager.current_phase == StartupPhase.COMPLETED and scene_composer is not None:
        return {"status": "ready", "message": "All models loaded and ready"}
    elif startup_manager and startup_manager.current_phase not in [StartupPhase.IDLE, StartupPhase.COMPLETED, StartupPhase.FAILED]:
        return JSONResponse(
            status_code=503,
            content={
                "status": "initializing", 
                "message": f"Models still loading... (Phase: {startup_manager.current_phase.value})"
            }
        )
    else:
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "message": "Initialization not started or failed"}
        )

@app.get("/warmup-status")
async def warmup_status():
    """Detailed warmup status including cache and benchmark information"""
    global startup_manager
    
    # Get detailed status from startup manager if available
    if startup_manager:
        metrics = startup_manager.get_metrics()
        status = startup_manager.get_status()
        
        # Enhanced status with startup manager data
        return {
            "startup_manager": {
                "phase": startup_manager.current_phase.value,
                "initialized": startup_manager.current_phase == StartupPhase.COMPLETED,
                "metrics": {
                    "total_time": metrics.total_time,
                    "environment_setup_time": metrics.environment_setup_time,
                    "flash_attention_time": metrics.flash_attention_time,
                    "device_detection_time": metrics.device_detection_time,
                    "warmup_detection_time": metrics.warmup_detection_time,
                    "adapter_creation_time": metrics.adapter_creation_time,
                    "scene_composer_time": metrics.scene_composer_time,
                    "route_injection_time": metrics.route_injection_time
                }
            },
            "warmup_status": {
                "worked": status.get("warmup_detected", False),
                "flash_attention_available": status.get("flash_attention_available", False),
                "total_cache_size_gb": status.get("cache_size_gb", 0),
                "benchmark_results": _get_warmup_benchmark_results()
            },
            "cache_directories": status.get("cache_info", {}),
            "device_info": status.get("device_info", {}),
            "initialization_status": {
                "phase": startup_manager.current_phase.value,
                "complete": startup_manager.current_phase == StartupPhase.COMPLETED,
                "in_progress": startup_manager.current_phase not in [StartupPhase.IDLE, StartupPhase.COMPLETED, StartupPhase.FAILED],
                "scene_composer_ready": scene_composer is not None
            }
        }
    
    # Fallback to basic cache check if startup manager not available
    cache_dirs = [
        os.environ.get('HF_HOME'),
        os.environ.get('TRANSFORMERS_CACHE'),
        os.environ.get('HF_HUB_CACHE'),
    ]
    # Remove any None values
    cache_dirs = [d for d in cache_dirs if d]
    
    cache_info = {}
    total_cache_size = 0
    
    for cache_dir in cache_dirs:
        if os.path.exists(cache_dir):
            try:
                # Quick size calculation
                size = 0
                files = 0
                for root, dirs, filenames in os.walk(cache_dir):
                    files += len(filenames)
                    for filename in filenames:
                        try:
                            size += os.path.getsize(os.path.join(root, filename))
                        except OSError:
                            pass
                
                size_gb = size / (1024**3)
                total_cache_size += size_gb
                
                cache_info[cache_dir] = {
                    "exists": True,
                    "files": files,
                    "size_gb": round(size_gb, 2)
                }
            except Exception as e:
                cache_info[cache_dir] = {"exists": True, "error": str(e)}
        else:
            cache_info[cache_dir] = {"exists": False}
    
    # Check benchmark results
    benchmark_info = {"exists": False}
    benchmark_file = Path('/tmp/benchmark_results/latest_build_benchmark.json')
    
    if benchmark_file.exists():
        try:
            with open(benchmark_file, 'r') as f:
                data = json.load(f)
            
            warmup_data = data.get('benchmarks', {}).get('model_warmup', {})
            benchmark_info = {
                "exists": True,
                "success": warmup_data.get('success', False),
                "total_time": warmup_data.get('total_time', 0),
                "cache_size_gb": warmup_data.get('final_cache_size_gb', 0),
                "timestamp": data.get('timestamp', 'Unknown')
            }
        except Exception as e:
            benchmark_info = {"exists": True, "error": str(e)}
    
    # Determine warmup status
    warmup_worked = (
        total_cache_size > 2.0 and  # At least 2GB of cached models
        benchmark_info.get("success", False)  # Benchmark shows success
    )
    
    return {
        "startup_manager": {"available": False, "reason": "Not initialized yet"},
        "warmup_status": {
            "worked": warmup_worked,
            "total_cache_size_gb": round(total_cache_size, 2),
            "benchmark_results": _get_warmup_benchmark_results()
        },
        "cache_directories": cache_info,
        "benchmark_results": benchmark_info,
        "initialization_status": {
            "phase": "unknown",
            "complete": False,
            "in_progress": False,
            "scene_composer_ready": scene_composer is not None
        }
    }

if __name__ == "__main__":
    import uvicorn
    # Load server config for host, port, and log level
    cfg = get_config()
    server_cfg = cfg.get("server", {})
    host = server_cfg.get("host") or os.getenv("HOST") or "0.0.0.0"
    port = server_cfg.get("port") or int(os.getenv("PORT", "7860"))
    log_level = server_cfg.get("log_level", "info")
    uvicorn.run(
        "app:app",
        host=host,
        port=port,
        log_level=log_level,
        reload=True
    )
