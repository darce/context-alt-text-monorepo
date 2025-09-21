#!/usr/bin/env python3
"""
Startup Manager - Centralized orchestration for model loading, dependency management, and library initialization.

This module provides a comprehensive startup management system that:
- Manages Flash Attention setup and availability checking
- Handles environment configuration and cache directory setup
- Orchestrates model warmup detection and cold start optimization
- Provides centralized adapter initialization with proper ordering
- Manages device detection and resolution
- Handles graceful fallbacks and error recovery
- Provides detailed timing and performance metrics
- Supports background initialization with status tracking
"""

import os
import time
import logging
import threading
import subprocess
import importlib.util
from datetime import datetime
from typing import Dict, Any, Optional, Tuple, List, Callable
from pathlib import Path
from dataclasses import dataclass, field
from shared.enums.startup_phase import StartupPhase

from analysis.workflow.scene_composer import SceneComposer
from shared.startup.adapter_factory import AdapterFactory
from shared.config.settings import get_config
from shared.infrastructure.gpu_manager import get_gpu_manager
from shared.infrastructure.attention_optimizers import (
    get_attention_manager, AttentionOptimizerManager
)
from shared.infrastructure.ports.attention_optimizer_base import AttentionConfig
from shared.enums.attention_backend import AttentionBackend
from shared.utils.device_utils import get_available_device


@dataclass
class StartupMetrics:
    """Container for startup timing and performance metrics."""
    total_time: float = 0.0
    environment_setup_time: float = 0.0
    flash_attention_time: float = 0.0
    device_detection_time: float = 0.0
    warmup_detection_time: float = 0.0
    adapter_creation_time: float = 0.0
    scene_composer_time: float = 0.0
    route_injection_time: float = 0.0
    warmup_detected: bool = False
    flash_attention_available: bool = False
    primary_device: str = "cpu"
    adapters_initialized: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


@dataclass
class StartupConfig:
    """Configuration options for startup manager. All values loaded from settings.yaml."""
    background_initialization: bool
    warmup_check_enabled: bool
    flash_attention_check_enabled: bool
    device_auto_detection: bool
    adapter_initialization_order: List[str]
    startup_timeout: float
    enable_metrics: bool
    verbose_logging: bool
    
    @classmethod
    def from_config(cls, config_dict: dict) -> 'StartupConfig':
        """Create StartupConfig from settings.yaml configuration."""
        return cls(
            background_initialization=config_dict.get('background_initialization', True),
            warmup_check_enabled=config_dict.get('warmup_check_enabled', True),
            flash_attention_check_enabled=config_dict.get('flash_attention_check_enabled', True),
            device_auto_detection=config_dict.get('device_auto_detection', True),
            adapter_initialization_order=config_dict.get('adapter_initialization_order', [
                "caption_generator", "object_detector", "entity_identifier"
            ]),
            startup_timeout=float(config_dict.get('timeout_seconds', 300.0)),
            enable_metrics=config_dict.get('enable_metrics', True),
            verbose_logging=config_dict.get('verbose_logging', True)
        )


class StartupManager:
    """
    Centralized startup manager for the Entity Identifier API.
    
    This class orchestrates the entire application startup process, including:
    - Environment setup and validation
    - Flash Attention detection and configuration
    - Device detection and resolution
    - Model warmup detection
    - Adapter creation and initialization
    - Scene composer setup
    - Route injection and dependency management
    """
    
    def __init__(self, config: StartupConfig):
        """
        Initialize the StartupManager with required configuration.
        
        Args:
            config: StartupConfig instance loaded from settings.yaml
        """
        self.config = config
        self.metrics = StartupMetrics()
        self.current_phase = StartupPhase.IDLE
        self.scene_composer: Optional[SceneComposer] = None
        self.device = get_available_device()
        
        # Thread safety
        self._lock = threading.Lock()
        self._is_initializing = False
        self._initialization_complete = False
        self._initialization_error: Optional[Exception] = None
        
        # Callbacks for status updates
        self._status_callbacks: List[Callable[[StartupPhase, StartupMetrics], None]] = []
        
        # Setup logging
        self.logger = logging.getLogger(__name__)
        if self.config.verbose_logging:
            self.logger.setLevel(logging.INFO)
    
    def add_status_callback(self, callback: Callable[[StartupPhase, StartupMetrics], None]):
        """Add a callback to be notified of startup phase changes."""
        self._status_callbacks.append(callback)
    
    def _update_phase(self, phase: StartupPhase):
        """Update the current startup phase and notify callbacks."""
        self.current_phase = phase
        for callback in self._status_callbacks:
            try:
                callback(phase, self.metrics)
            except Exception as e:
                self.logger.warning(f"Status callback error: {e}")
    
    def _measure_time(self, operation_name: str):
        """Context manager for measuring operation timing."""
        class TimingContext:
            def __init__(self, manager, name):
                self.manager = manager
                self.name = name
                self.start_time = None
            
            def __enter__(self):
                self.start_time = time.time()
                return self
            
            def __exit__(self, exc_type, exc_val, exc_tb):
                duration = time.time() - self.start_time
                setattr(self.manager.metrics, f"{self.name}_time", duration)
                if self.manager.config.verbose_logging:
                    self.manager.logger.info(f"📊 [{self.name.upper()}] {duration:.2f}s")
        
        return TimingContext(self, operation_name)
    
    def is_ready(self) -> bool:
        """Check if startup is complete and the system is ready."""
        with self._lock:
            return self._initialization_complete and self.scene_composer is not None
    
    def is_initializing(self) -> bool:
        """Check if initialization is currently in progress."""
        with self._lock:
            return self._is_initializing
    
    def get_initialization_error(self) -> Optional[Exception]:
        """Get any error that occurred during initialization."""
        with self._lock:
            return self._initialization_error
    
    def setup_environment(self) -> Dict[str, str]:
        """Setup environment variables and cache directories."""
        self._update_phase(StartupPhase.ENVIRONMENT_SETUP)
        
        with self._measure_time("environment_setup"):
            try:
                # Import and setup environment from shared config module
                from shared.config import setup_environment, settings
                from shared.utils.version import __version__ as version
                # Setup cache environment variables
                cache_dirs = setup_environment()
                # Store cache dirs for later warmup detection
                self.cache_dirs = cache_dirs
                env_mode = settings.get('env_mode')
                self.logger.info(f"🔧 [ENV] Mode: {env_mode}, Version: {version}")
                self.logger.info(f"🔧 [ENV] Cache directories configured: {len(cache_dirs)} dirs")
                return cache_dirs
            except Exception as e:
                error_msg = f"Environment setup failed: {e}"
                self.metrics.errors.append(error_msg)
                self.logger.error(f"❌ [ENV] {error_msg}")
                raise

    def check_flash_attention(self) -> bool:
        """Check Flash Attention availability and setup attention optimizations."""
        self._update_phase(StartupPhase.FLASH_ATTENTION_CHECK)
        
        with self._measure_time("flash_attention"):
            if not self.config.flash_attention_check_enabled:
                self.logger.info("⚡ [ATTENTION] Check disabled by configuration")
                return False
            
            try:
                # Log comprehensive GPU information first using gpu_core
                gpu_manager = get_gpu_manager()
                gpu_manager.log_gpu_info()
                
                # Get GPU compute capability for architecture-specific optimizations
                gpu_info = gpu_manager.get_gpu_info("phi3")
                gpu_compute_cap = gpu_info.compute_capability if gpu_info else None
                
                # Convert tuple to float for comparison
                gpu_compute_float = None
                if gpu_compute_cap:
                    major, minor = gpu_compute_cap
                    gpu_compute_float = major + (minor / 10.0)
                
                # Detect primary device for attention optimization
                device = gpu_manager.detect_best_device()
                
                # Get architecture-specific attention configuration for Phi-3
                phi3_config = gpu_manager.get_attention_config("phi3")
                recommended_attention = phi3_config.get("attn_implementation", "eager")
                
                self.logger.info(f"🎯 [PHI3] Recommended attention for GPU {gpu_compute_cap}: {recommended_attention}")
                
                # Initialize attention manager with architecture-aware config
                attention_config = AttentionConfig(
                    log_selection=True,
                    enable_benchmarking=True
                )
                attention_manager = get_attention_manager(attention_config)
                
                # Get the best attention optimizer for this device
                optimizer = attention_manager.get_best_optimizer(device)
                selected_backend = optimizer.backend_type
                
                # Log comprehensive attention summary
                attention_manager.log_attention_summary(device)
                
                # Handle GPU architecture specific optimizations
                if gpu_compute_float:
                    if gpu_compute_float == 7.5:  # T4 GPU
                        self.logger.info("🔥 [T4-GPU] Detected T4 GPU - optimizing for T4 architecture")
                        
                        # For Phi3V models on T4, always use eager attention
                        if "phi3" in device.lower() or recommended_attention == "sdpa":
                            self.logger.info("🔧 [T4-PHI3] Forcing eager attention for Phi3 on T4 GPU")
                            recommended_attention = "eager"
                        
                        if recommended_attention != "flash_attention_2":
                            self.logger.info("⚡ [T4-OPT] Flash Attention v2 not supported on T4")
                            
                            if recommended_attention == "sdpa":
                                self.logger.info("🚀 [T4-OPT] Selected optimization: SDPA attention for Phi-3")
                            elif recommended_attention == "eager":
                                self.logger.info("🔧 [T4-OPT] Using eager attention for compatibility")
                        
                        # Enable GPU optimizations
                        self._apply_gpu_runtime_optimizations()
                        
                    elif gpu_compute_float >= 8.0:  # Newer GPUs (Ampere, Ada Lovelace)
                        self.logger.info(f"🚀 [GPU] Detected newer GPU (compute {gpu_compute_float}) - enabling advanced optimizations")
                        
                        if recommended_attention == "flash_attention_2":
                            self.logger.info("⚡ [FLASH-ATTN-V2] Using Flash Attention v2 for maximum performance")
                        elif recommended_attention == "sdpa":
                            self.logger.info("⚡ [TRITON] Using SDPA attention as fallback")
                            
                    elif gpu_compute_float >= 7.0:  # Volta (V100)
                        self.logger.info(f"🔥 [GPU] Detected Volta GPU (compute {gpu_compute_float}) - using SDPA optimizations")
                        
                        if recommended_attention == "sdpa":
                            self.logger.info("⚡ [SDPA] Using SDPA attention for V100")
                else:
                    self.logger.info("🔧 [CPU/MPS] Using eager attention for non-CUDA devices")
                
                # Store the attention manager for later use
                self._attention_manager = attention_manager
                
                # Return True if we have any optimization beyond eager
                optimized = selected_backend != AttentionBackend.EAGER
                self.metrics.flash_attention_available = optimized
                
                if optimized:
                    capabilities = optimizer.get_capabilities(device)
                    speedup = capabilities.speed_improvement or 1.0
                    self.logger.info(f"⚡ [ATTENTION] Optimization enabled: {selected_backend.value} ({speedup:.1f}x speedup)")
                else:
                    self.logger.info("⚡ [ATTENTION] Using standard eager attention")
                
                return optimized
                
            except Exception as e:
                error_msg = f"Attention optimization check failed: {e}"
                self.metrics.errors.append(error_msg)
                self.logger.error(f"❌ [ATTENTION] {error_msg}")
                return False
    
    def _apply_gpu_runtime_optimizations(self):
        """Apply runtime optimizations for the detected GPU architecture using canonical config."""
        config = get_config()
        gpu_manager = get_gpu_manager()
        gpu_info = gpu_manager.get_gpu_info()
        if not gpu_info:
            self.logger.info("No CUDA GPU detected, skipping GPU runtime optimizations.")
            return

        major, minor = gpu_info.compute_capability
        gpu_arch = f"{major + (minor / 10.0):.1f}"
        try:
            gpu_configs = config['runtime_optimizations']['gpu_configs']
            gpu_config = gpu_configs.get(gpu_arch)
            if not gpu_config:
                self.logger.warning(f"No runtime_optimizations config for GPU arch {gpu_arch}")
                return
        except KeyError as e:
            self.logger.error(f"Missing runtime_optimizations config: {e}")
            return

        # Set environment variables from config (if needed, but do not read from os.environ directly)
        if 'max_split_size_mb' in gpu_config:
            os.environ['PYTORCH_CUDA_ALLOC_CONF'] = f"max_split_size_mb:{gpu_config['max_split_size_mb']}"
        if 'cuda_memory_fraction' in gpu_config:
            os.environ['CUDA_MEMORY_FRACTION'] = str(gpu_config['cuda_memory_fraction'])
        if 'enable_memory_optimization' in gpu_config:
            os.environ['ENABLE_MEMORY_OPTIMIZATION'] = str(gpu_config['enable_memory_optimization']).lower()
        self.logger.info(f"🔥 [GPU-OPT] Enabled runtime optimizations for arch {gpu_arch} (from config via settings.py)")
        self.logger.info(f"⚡ [GPU-OPT] Memory fraction: {gpu_config.get('cuda_memory_fraction', 'N/A')}, Max split: {gpu_config.get('max_split_size_mb', 'N/A')}MB")
        self.logger.info(f"🎯 [GPU-OPT] Flash Attention v2 enabled: {gpu_config.get('flash_attention_enabled', 'N/A')}, recommended: {gpu_config.get('recommended_attention', 'N/A')}")

    def detect_compute_environment(self) -> str:
        """Detect and configure the optimal compute environment."""
        self._update_phase(StartupPhase.DEVICE_DETECTION)
        
        with self._measure_time("device_detection"):
            try:
                if self.config.device_auto_detection:
                    device = get_gpu_manager().detect_best_device()
                    self.metrics.primary_device = device
                    get_gpu_manager().log_gpu_info()
                    return device
                else:
                    config = get_config()
                    device_spec = config.get('environment', {}).get('primary_device', 'auto')
                    device = get_gpu_manager().resolve_device_spec(device_spec)
                    self.metrics.primary_device = device
                    self.logger.info(f"🖥️ [DEVICE] Configured device: {device}")
                    return device
            except Exception as e:
                error_msg = f"Device detection failed: {e}"
                self.metrics.errors.append(error_msg)
                self.logger.error(f"❌ [DEVICE] {error_msg}")
                self.metrics.primary_device = 'cpu'
                return 'cpu'

    def check_model_warmup(self) -> bool:
        """Check if models were pre-warmed during build."""
        self._update_phase(StartupPhase.WARMUP_DETECTION)
        
        with self._measure_time("warmup_detection"):
            if not self.config.warmup_check_enabled:
                return False
            
            try:
                # Use cache_dirs set during setup_environment
                cache_dir = getattr(self, 'cache_dirs', {}).get('HF_HOME')
                warmup_detected = os.path.exists(cache_dir) and len(os.listdir(cache_dir)) > 0
                self.metrics.warmup_detected = warmup_detected
                
                if warmup_detected:
                    # Count cached models
                    try:
                        model_count = len([d for d in os.listdir(cache_dir) 
                                        if os.path.isdir(os.path.join(cache_dir, d))])
                        self.logger.info(f"🔥 [WARMUP] Detected {model_count} pre-cached models")
                    except:
                        self.logger.info("🔥 [WARMUP] Pre-warmed models detected")
                else:
                    self.logger.info("🧊 [WARMUP] Cold start - downloading models from scratch")
                
                return warmup_detected
                
            except Exception as e:
                warning = f"Warmup detection failed: {e}"
                self.metrics.warnings.append(warning)
                self.logger.warning(f"⚠️ [WARMUP] {warning}")
                return False
    
    def create_adapters(self) -> Tuple[Any, Any, Any, Optional[Any]]:
        """Create and initialize all adapters, including caption pipeline."""
        self._update_phase(StartupPhase.ADAPTER_CREATION)
        
        with self._measure_time("adapter_creation"):
            config = get_config()
            adapters_config = config["adapters"]
            
            self.logger.info("🔧 [ADAPTERS] Creating adapters...")
            
            # Create adapters using factory
            object_detector, entity_identifier, caption_generator = AdapterFactory.create_adapters(adapters_config)
            # Inject roster_service into entity_identifier so FaissIndex can use it
            try:
                from api.dependencies import get_roster_service
                roster_srv = get_roster_service()
                if entity_identifier:
                    entity_identifier.roster_service = roster_srv
                self.logger.info("🔌 [STARTUP] Injected roster_service into entity_identifier for FaissIndex")
            except Exception as e:
                self.logger.warning(f"🔌 [STARTUP] Could not inject roster_service into entity_identifier: {e}")
            
            # Initialize caption pipeline if caption generator exists
            caption_pipeline = None
            if caption_generator:
                caption_pipeline = self.initialize_caption_pipeline(caption_generator)
            
            # Track which adapters were initialized with detailed info
            adapter_details = []
            adapter_map = {
                "object_detector": (object_detector, adapters_config.get("object_detector", {}).get("type", "unknown")),
                "entity_identifier": (entity_identifier, adapters_config.get("entity_identifier", {}).get("type", "stub")),
                "caption_generator": (caption_generator, adapters_config.get("caption_generator", {}).get("type", "unknown"))
            }
            
            for name, (adapter, adapter_type) in adapter_map.items():
                if hasattr(adapter, 'is_ready') and adapter.is_ready():
                    self.metrics.adapters_initialized.append(name)
                    adapter_details.append(f"{name}({adapter_type})")
                else:
                    adapter_details.append(f"{name}({adapter_type})[NOT_READY]")
            
            self.logger.info(f"✅ [ADAPTERS] Created {len(self.metrics.adapters_initialized)}/{len(adapter_map)} adapters: {', '.join(adapter_details)}")
            
            return object_detector, entity_identifier, caption_generator, caption_pipeline
    
    def create_scene_composer(self, object_detector, entity_identifier, caption_generator) -> SceneComposer:
        """Create and configure the scene composer."""
        self._update_phase(StartupPhase.SCENE_COMPOSER_INIT)
        
        with self._measure_time("scene_composer"):
            try:
                # Count and list the adapters being passed
                adapters = {
                    "object_detector": object_detector,
                    "entity_identifier": entity_identifier, 
                    "caption_generator": caption_generator
                }
                
                # Filter out None adapters to get actual count
                active_adapters = {name: adapter for name, adapter in adapters.items() if adapter is not None}
                adapter_names = list(active_adapters.keys())
                
                self.logger.info(f"🎭 [COMPOSER] Creating scene composer with {len(active_adapters)} adapters: {', '.join(adapter_names)}")
                
                # Support registry pattern for entity identifiers
                entity_identifiers = [entity_identifier] if entity_identifier else []
                
                scene_composer = SceneComposer(
                    object_detector=object_detector,
                    entity_identifiers=entity_identifiers,
                    caption_generator=caption_generator
                )
                
                self.scene_composer = scene_composer
                self.logger.info(f"✅ [COMPOSER] Scene composer created successfully with {len(active_adapters)} adapters")
                
                return scene_composer
                
            except Exception as e:
                error_msg = f"Scene composer creation failed: {e}"
                self.metrics.errors.append(error_msg)
                self.logger.error(f"❌ [COMPOSER] {error_msg}")
                raise
    
    def inject_dependencies(self, scene_composer: SceneComposer):
        """Inject dependencies into API routes and other components."""
        self._update_phase(StartupPhase.ROUTE_INJECTION)
        
        with self._measure_time("route_injection"):
            try:
                injected_dependencies = []
                
                self.logger.info("🔌 [INJECTION] Injecting dependencies...")
                
                # Inject scene composer into routes
                from api.routes.main import set_scene_composer
                set_scene_composer(scene_composer)
                injected_dependencies.append("scene_composer → api.routes.main")
                
                # Create and inject scene analysis service
                from analysis.services.scene_analysis_service import SceneAnalysisService
                from api.routes.main import set_scene_analysis_service
                scene_analysis_service = SceneAnalysisService(scene_composer)
                set_scene_analysis_service(scene_analysis_service)
                injected_dependencies.append("scene_analysis_service → api.routes.main")
                
                # Log successful injections with details
                self.logger.info(f"✅ [INJECTION] Dependencies injected: {', '.join(injected_dependencies)}")
                
            except Exception as e:
                error_msg = f"Dependency injection failed: {e}"
                self.metrics.errors.append(error_msg)
                self.logger.error(f"❌ [INJECTION] {error_msg}")
                raise
    
    def initialize_sync(self) -> SceneComposer:
        """
        Perform synchronous initialization of all components.
        
        Returns:
            SceneComposer: The initialized scene composer
            
        Raises:
            RuntimeError: If initialization fails
        """
        start_time = time.time()
        
        try:
            self.logger.info("🚀 [STARTUP] Beginning synchronous initialization...")
            
            # Setup environment
            self.setup_environment()
            
            # Check Flash Attention
            self.check_flash_attention()
            
            # Detect compute environment
            self.detect_compute_environment()
            
            # Check model warmup with smart loading integration
            warmup_detected = self.check_model_warmup()
            
            # Create adapters with smart loading configuration and initialize caption pipeline
            object_detector, entity_identifier, caption_generator, caption_pipeline = self.create_adapters()
            
            # Store the caption pipeline for potential use by the application
            self.caption_pipeline = caption_pipeline
            
            # Create scene composer
            scene_composer = self.create_scene_composer(object_detector, entity_identifier, caption_generator)
            
            # Inject dependencies
            self.inject_dependencies(scene_composer)
            
            # Complete initialization
            self.metrics.total_time = time.time() - start_time
            self._update_phase(StartupPhase.COMPLETED)
            
            with self._lock:
                self._initialization_complete = True
                self._is_initializing = False
            
            self._log_startup_summary()
            
            return scene_composer
            
        except Exception as e:
            self.metrics.total_time = time.time() - start_time
            self._update_phase(StartupPhase.FAILED)
            
            with self._lock:
                self._initialization_error = e
                self._is_initializing = False
            
            self.logger.error(f"❌ [STARTUP] Initialization failed: {e}")
            raise RuntimeError(f"Startup initialization failed: {e}") from e
    
    def initialize_async(self, callback: Optional[Callable[[SceneComposer], None]] = None):
        """
        Perform asynchronous initialization in a background thread.
        
        Args:
            callback: Optional callback to call when initialization completes
        """
        with self._lock:
            if self._initialization_complete or self._is_initializing:
                return
            
            self._is_initializing = True
        
        def background_init():
            try:
                scene_composer = self.initialize_sync()
                if callback:
                    callback(scene_composer)
            except Exception as e:
                self.logger.error(f"❌ [STARTUP] Background initialization failed: {e}")
        
        init_thread = threading.Thread(target=background_init, daemon=True)
        init_thread.start()
        
        self.logger.info("🚀 [STARTUP] Background initialization started...")
    
    def initialize(self) -> SceneComposer:
        """
        Initialize the startup manager using the configured initialization mode.
        
        Returns:
            SceneComposer: The initialized scene composer
        """
        if self.config.background_initialization:
            self.initialize_async()
            # For background initialization, wait a moment to ensure it starts
            time.sleep(0.1)
            return self.scene_composer
        else:
            return self.initialize_sync()
    
    def get_attention_manager(self):
        """Get the initialized attention manager."""
        return getattr(self, '_attention_manager', None)
    
    def get_metrics(self) -> StartupMetrics:
        """Get the current startup metrics."""
        return self.metrics
    
    def get_caption_pipeline(self) -> Optional[Any]:
        """Get the initialized caption generation pipeline."""
        return getattr(self, 'caption_pipeline', None)
    
    def get_status(self) -> Dict[str, Any]:
        """Get the current startup status and configuration details."""
        # Basic status
        status = {
            "current_phase": self.current_phase.value,
            "is_ready": self._initialization_complete,
            "is_initializing": self._is_initializing,
            "warmup_detected": self.metrics.warmup_detected,
            "flash_attention_available": self.metrics.flash_attention_available,
            "primary_device": self.metrics.primary_device,
            "adapters_initialized": self.metrics.adapters_initialized.copy(),
            "warnings": self.metrics.warnings.copy(),
            "errors": self.metrics.errors.copy()
        }
        # Cache information (do not read from os.environ, use config if needed)
        config = get_config()
        cache_info = {}
        cache_dirs = config.get('environment', {}).get('cache_dirs', [])
        total_cache_size = 0
        for cache_dir in cache_dirs:
            if os.path.exists(cache_dir):
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
            else:
                cache_info[cache_dir] = {"exists": False}
        status["cache_info"] = cache_info
        status["cache_size_gb"] = round(total_cache_size, 2)
        # Device information
        device_info = {}
        if self.metrics.primary_device:
            device_info["primary"] = self.metrics.primary_device
            if self.metrics.primary_device == "cuda":
                try:
                    import torch
                    if torch.cuda.is_available():
                        device_info["cuda_devices"] = torch.cuda.device_count()
                        device_info["cuda_memory_gb"] = round(
                            torch.cuda.get_device_properties(0).total_memory / (1024**3), 2
                        )
                except:
                    pass
        status["device_info"] = device_info
        return status
    
    def _log_startup_summary(self):
        """Log a comprehensive summary of the startup process."""
        self.logger.info("🎯 [STARTUP] ======== INITIALIZATION COMPLETE ========")
        
        # Overall timing
        self.logger.info(f"⏱️ [STARTUP] Total time: {self.metrics.total_time:.2f}s")
        
        # Phase breakdown
        phases = [
            ("Environment Setup", self.metrics.environment_setup_time),
            ("Flash Attention Check", self.metrics.flash_attention_time),
            ("Device Detection", self.metrics.device_detection_time),
            ("Warmup Detection", self.metrics.warmup_detection_time),
            ("Adapter Creation", self.metrics.adapter_creation_time),
            ("Scene Composer Init", self.metrics.scene_composer_time),
            ("Route Injection", self.metrics.route_injection_time),
        ]
        
        for phase_name, phase_time in phases:
            if phase_time > 0:
                percentage = (phase_time / self.metrics.total_time) * 100 if self.metrics.total_time > 0 else 0
                self.logger.info(f"📊 [STARTUP] {phase_name}: {phase_time:.2f}s ({percentage:.1f}%)")
        
        # Key findings
        self.logger.info(f"🖥️ [STARTUP] Primary device: {self.metrics.primary_device}")
        self.logger.info(f"⚡ [STARTUP] Flash Attention: {'Available' if self.metrics.flash_attention_available else 'Not available'}")
        self.logger.info(f"🔥 [STARTUP] Models pre-warmed: {'Yes' if self.metrics.warmup_detected else 'No'}")
        self.logger.info(f"🔧 [STARTUP] Adapters initialized: {len(self.metrics.adapters_initialized)}")
        
        # Warnings and errors
        if self.metrics.warnings:
            self.logger.info(f"⚠️ [STARTUP] Warnings: {len(self.metrics.warnings)}")
            for warning in self.metrics.warnings:
                self.logger.warning(f"⚠️ [STARTUP] {warning}")
        
        if self.metrics.errors:
            self.logger.info(f"❌ [STARTUP] Errors: {len(self.metrics.errors)}")
            for error in self.metrics.errors:
                self.logger.error(f"❌ [STARTUP] {error}")
        
        self.logger.info("✅ [STARTUP] Application ready to serve requests!")
        from shared.utils.version import __version__
        print(f"✅ [STARTUP] Application version: {__version__} is ready to serve requests!")

    def initialize_caption_pipeline(self, caption_adapter) -> Optional[Any]:
        """
        Initialize the caption generation pipeline from the given adapter.
        This is called during startup to prepare the pipeline for use.
        """
        self.logger.info("🖼️ [PIPELINE] Initializing caption generation pipeline...")
        
        try:
            # Handle different adapter types appropriately
            if hasattr(caption_adapter, 'model_loader') and caption_adapter.model_loader:
                # Real adapter with model loader (e.g., Phi3CaptionAdapter)
                pipeline = caption_adapter.model_loader.load_pipeline()
                self.logger.info("✅ [PIPELINE] Caption pipeline ready via %s '%s'", 
                    type(caption_adapter).__name__, caption_adapter.model_id)
                return pipeline
            else:
                # Mock adapter or adapter without model loader
                self.logger.info("ℹ️ [PIPELINE] Mock caption adapter loaded: %s - no pipeline needed", 
                    type(caption_adapter).__name__)
                return None
                
        except Exception as e:
            error_msg = f"Caption pipeline initialization failed: {e}"
            self.metrics.errors.append(error_msg)
            self.logger.error(f"❌ [PIPELINE] {error_msg}")
            return None


# Global startup manager instance
_startup_manager: Optional[StartupManager] = None


def get_startup_manager(config: StartupConfig) -> StartupManager:
    """Get or create the global startup manager instance with required config."""
    global _startup_manager
    if _startup_manager is None:
        _startup_manager = StartupManager(config)
    return _startup_manager


def initialize_application(background: bool = True, *, config: StartupConfig) -> Optional[SceneComposer]:
    """
    Initialize the application using the startup manager.
    
    Args:
        background: Whether to initialize in the background
        config: Required startup configuration loaded from settings.yaml
        
    Returns:
        SceneComposer if synchronous initialization, None if background
    """
    manager = get_startup_manager(config)
    
    if background:
        manager.initialize_async()
        return None
    else:
        return manager.initialize_sync()
