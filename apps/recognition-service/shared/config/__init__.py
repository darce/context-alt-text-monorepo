"""
Platform Configuration Management
"""

import os
import platform
import logging
from pathlib import Path
from typing import Dict
from dotenv import load_dotenv  # type: ignore[import]
from .settings import get_config

# Load environment variables from .env file
load_dotenv()

def _infer_default_cache_root() -> Path:
    """Determine a cache root based on environment and runtime context."""
    for env_var in ("CACHE_DIR", "LOCAL_CACHE_ROOT"):
        value = os.getenv(env_var)
        if value:
            return Path(value)

    # Hugging Face deployments define HF_HOME/HF_HUB_CACHE
    hf_home = os.getenv("HF_HOME")
    if hf_home:
        return Path(hf_home)

    for env_var in ("HF_HUB_CACHE", "TRANSFORMERS_CACHE"):
        value = os.getenv(env_var)
        if value:
            candidate = Path(value)
            return candidate.parent if candidate.is_file() else candidate

    if platform.system() == "Darwin":
        butter = Path("/Volumes/Butter")
        if butter.exists():
            return butter

    return Path.home() / ".cache" / "context-alt-text"


def _ensure_leaf(base: Path, leaf: str) -> Path:
    return base if base.name.lower() == leaf else base / leaf


def setup_environment() -> Dict[str, str]:
    """
    Setup environment variables from YAML settings and ENV overrides.
    Expects the following to be set via ENV or settings:
    - CACHE_DIR: base directory for all caches
    """
    # Get configuration from settings.yaml
    config = get_config()
    startup_cfg = config.get('startup', {})
    
    # Get base cache directory from environment or settings
    base_cache_dir = os.getenv('CACHE_DIR') or startup_cfg.get('cache_dir')
    if not base_cache_dir:
        base_cache_dir = str(_infer_default_cache_root())

    base_cache_path = Path(base_cache_dir)
    
    # Create base cache directory
    os.makedirs(base_cache_path, exist_ok=True)
    
    # Define specific cache paths under base directory
    hf_cache_dir = os.path.join(str(base_cache_path), 'huggingface_cache')
    cache_dirs = {
        'HF_HOME': hf_cache_dir,
        'HF_HUB_CACHE': hf_cache_dir,
        'TRANSFORMERS_CACHE': hf_cache_dir,
    'TORCH_HOME': os.path.join(str(base_cache_path), 'torch'),
    'YOLO_CONFIG_DIR': os.path.join(str(base_cache_path), 'yolo'),
    'MPLCONFIGDIR': os.path.join(str(base_cache_path), 'matplotlib'),
    'INSIGHTFACE_CACHE_DIR': str(_ensure_leaf(base_cache_path, 'insightface')),
    }
    
    # Ensure CACHE_DIR is globally available
    os.environ['CACHE_DIR'] = str(base_cache_path)

    # Export cache environment variables
    for env_var, path in cache_dirs.items():
        try:
            os.makedirs(path, exist_ok=True)
            os.environ[env_var] = path
            logging.info(f"Set {env_var} to {path}")
        except (OSError, PermissionError) as e:
            logging.warning(f"Failed to create cache directory {path}: {e}")
            # Fallback to temp directory for this specific cache
            import tempfile
            fallback_path = os.path.join(tempfile.gettempdir(), os.path.basename(path))
            os.makedirs(fallback_path, exist_ok=True)
            os.environ[env_var] = fallback_path
            logging.info(f"Using fallback: Set {env_var} to {fallback_path}")
    
    # Set INSIGHTFACE_HOME to match INSIGHTFACE_CACHE_DIR for model downloads
    os.environ["INSIGHTFACE_HOME"] = cache_dirs["INSIGHTFACE_CACHE_DIR"]
    logging.info(f"Set INSIGHTFACE_HOME to {os.environ['INSIGHTFACE_HOME']}")
    
    # Expose a dedicated debug cache directory for debug crops
    debug_crop_dir = config.get('debug', {}).get('face_crop_dir', os.path.join(base_cache_dir, 'debug_crops'))
    os.environ["DEBUG_CROP_DIR"] = debug_crop_dir
    os.makedirs(debug_crop_dir, exist_ok=True)
    logging.info(f"Set DEBUG_CROP_DIR to {debug_crop_dir}")
    
    # Setup application data directories
    setup_data_directories(config)
    
    # Set environment mode
    env_mode = os.getenv('ENV_MODE', config.get('env_mode', 'production'))
    os.environ['ENV_MODE'] = env_mode
    logging.info(f"Environment mode: {env_mode}")
    
    logging.info(f"Environment setup complete.")
    return cache_dirs

def setup_data_directories(config: Dict) -> None:
    """
    Create application data directories from configuration.
    These are separate from cache directories and contain application data.
    Paths are resolved relative to current working directory.
    """
    try:
        # Roster storage directories
        roster_config = config.get('roster_storage', {}).get('config', {})
        roster_file_path = roster_config.get('roster_file_path', 'data/roster.json')
        backup_directory = roster_config.get('backup_directory', 'data/backups')
        
        # Resolve paths relative to current working directory
        roster_file_path = os.path.abspath(roster_file_path)
        backup_directory = os.path.abspath(backup_directory)
        
        # Create roster data directory
        os.makedirs(os.path.dirname(roster_file_path), exist_ok=True)
        os.makedirs(backup_directory, exist_ok=True)
        logging.info(f"Created roster data directories: {os.path.dirname(roster_file_path)}, {backup_directory}")
        
        # Media storage directories
        media_config = config.get('media_storage', {}).get('config', {})
        upload_directory = media_config.get('upload_directory', 'data/media')
        upload_directory = os.path.abspath(upload_directory)
        os.makedirs(upload_directory, exist_ok=True)
        logging.info(f"Created media upload directory: {upload_directory}")
        
        # Debug directories
        debug_config = config.get('debug', {})
        face_crop_dir = debug_config.get('face_crop_dir', 'data/debug/face_crops')
        face_crop_dir = os.path.abspath(face_crop_dir)
        os.makedirs(face_crop_dir, exist_ok=True)
        logging.info(f"Created debug face crop directory: {face_crop_dir}")
        
        # Create base data/visualizations directory for embedding visualizations
        visualizations_dir = os.path.abspath('data/visualizations')
        os.makedirs(visualizations_dir, exist_ok=True)
        logging.info(f"Created visualizations directory: {visualizations_dir}")
        
    except (OSError, PermissionError) as e:
        logging.warning(f"Failed to create some data directories: {e}")
        # Continue execution - the app can handle missing directories at runtime

# Create settings object with environment overrides
def get_merged_settings():
    """Get settings with environment variable overrides applied."""
    settings = get_config()
    
    # Apply environment overrides
    env_cache = os.getenv('CACHE_DIR')
    if env_cache:
        if 'startup' not in settings:
            settings['startup'] = {}
        settings['startup']['cache_dir'] = env_cache
    
    settings['env_mode'] = os.getenv('ENV_MODE', settings.get('env_mode', 'production'))
    settings['debug_crop_dir'] = os.getenv('DEBUG_CROP_DIR', settings.get('debug', {}).get('face_crop_dir'))
    
    return settings

# Create the merged settings object (for compatibility with old code)
settings = get_merged_settings()
