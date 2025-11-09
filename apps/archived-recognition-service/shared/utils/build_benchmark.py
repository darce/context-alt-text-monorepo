#!/usr/bin/env python3
"""
Automated benchmark script that runs during Docker build to measure model warmup performance.
This script measures and logs the warmup time, then saves results for comparison.
"""

import os
import time
import json
import sys
import traceback
from datetime import datetime
from pathlib import Path

# Configure logging for build environment
import logging
logging.basicConfig(
    level=logging.INFO,
    format='[BENCHMARK] %(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class BuildTimeBenchmark:
    def __init__(self):
        self.results = {
            'timestamp': datetime.now().isoformat(),
            'build_environment': self._get_build_environment(),
            'benchmarks': {}
        }
        
    def _get_build_environment(self):
        """Collect build environment information"""
        return {
            'python_version': sys.version,
            'cuda_available': self._check_cuda(),
            'memory_info': self._get_memory_info(),
            'disk_space': self._get_disk_space(),
            'cache_dir': os.environ.get('HF_HOME', '/tmp/.huggingface_cache')
        }
    
    def _check_cuda(self):
        """Check if CUDA is available"""
        try:
            import torch
            return {
                'available': torch.cuda.is_available(),
                'device_count': torch.cuda.device_count() if torch.cuda.is_available() else 0,
                'version': torch.version.cuda if torch.cuda.is_available() else None
            }
        except ImportError:
            return {'available': False, 'error': 'PyTorch not installed'}
    
    def _get_memory_info(self):
        """Get memory information"""
        try:
            with open('/proc/meminfo', 'r') as f:
                meminfo = f.read()
            
            total_mem = None
            available_mem = None
            
            for line in meminfo.split('\n'):
                if 'MemTotal:' in line:
                    total_mem = int(line.split()[1]) * 1024  # Convert KB to bytes
                elif 'MemAvailable:' in line:
                    available_mem = int(line.split()[1]) * 1024
                    
            return {
                'total_bytes': total_mem,
                'available_bytes': available_mem,
                'total_gb': round(total_mem / (1024**3), 2) if total_mem else None,
                'available_gb': round(available_mem / (1024**3), 2) if available_mem else None
            }
        except Exception as e:
            logger.warning(f"Could not get memory info: {e}")
            return {'error': str(e)}
    
    def _get_disk_space(self):
        """Get disk space information"""
        try:
            import shutil
            cache_dir = os.environ.get('HF_HOME', '/tmp/.huggingface_cache')
            
            total, used, free = shutil.disk_usage('/')
            cache_size = self._get_directory_size(cache_dir) if os.path.exists(cache_dir) else 0
            
            return {
                'total_bytes': total,
                'used_bytes': used,
                'free_bytes': free,
                'cache_size_bytes': cache_size,
                'total_gb': round(total / (1024**3), 2),
                'free_gb': round(free / (1024**3), 2),
                'cache_size_gb': round(cache_size / (1024**3), 2)
            }
        except Exception as e:
            logger.warning(f"Could not get disk space info: {e}")
            return {'error': str(e)}
    
    def _get_directory_size(self, path):
        """Calculate directory size in bytes"""
        total_size = 0
        try:
            for dirpath, dirnames, filenames in os.walk(path):
                for filename in filenames:
                    filepath = os.path.join(dirpath, filename)
                    if os.path.exists(filepath):
                        total_size += os.path.getsize(filepath)
        except Exception as e:
            logger.warning(f"Error calculating directory size: {e}")
        return total_size
    
    def benchmark_model_warmup(self):
        """Benchmark the model warmup process"""
        logger.info("🚀 Starting automated model warmup benchmark...")
        
        warmup_start = time.time()
        
        try:
            # Add current directory to Python path to enable utils imports
            current_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            if current_dir not in sys.path:
                sys.path.insert(0, current_dir)

            # Import and run the warmup
            logger.info("📦 Importing warmup module...")
            from shared.infrastructure.preload_model import download_model_files
            
            import_time = time.time() - warmup_start
            logger.info(f"✅ Import completed in {import_time:.2f}s")
            
            # Benchmark model download and caching
            model_start = time.time()
            success = download_model_files()
            model_time = time.time() - model_start
            
            total_time = time.time() - warmup_start
            
            # Get cache size after warmup
            cache_dir = os.environ.get('HF_HOME', '/tmp/.huggingface_cache')
            final_cache_size = self._get_directory_size(cache_dir)
            
            benchmark_result = {
                'success': success,
                'total_time': total_time,
                'import_time': import_time,
                'model_warmup_time': model_time,
                'final_cache_size_bytes': final_cache_size,
                'final_cache_size_gb': round(final_cache_size / (1024**3), 2),
                'timestamp': datetime.now().isoformat()
            }
            
            if success:
                logger.info(f"🎉 Model warmup completed successfully!")
                logger.info(f"📊 Total time: {total_time:.2f}s")
                logger.info(f"📊 Model warmup time: {model_time:.2f}s") 
                logger.info(f"📊 Cache size: {benchmark_result['final_cache_size_gb']:.2f}GB")
            else:
                logger.error("❌ Model warmup failed!")
                
            self.results['benchmarks']['model_warmup'] = benchmark_result
            return benchmark_result
            
        except Exception as e:
            error_result = {
                'success': False,
                'error': str(e),
                'traceback': traceback.format_exc(),
                'total_time': time.time() - warmup_start,
                'timestamp': datetime.now().isoformat()
            }
            
            logger.error(f"❌ Model warmup benchmark failed: {e}")
            logger.error(f"Traceback: {error_result['traceback']}")
            
            self.results['benchmarks']['model_warmup'] = error_result
            return error_result
    
    def benchmark_import_times(self):
        """Benchmark key import times"""
        logger.info("📦 Benchmarking import times...")
        
        imports_to_test = [
            ('torch', 'import torch'),
            ('transformers', 'from transformers import AutoModelForCausalLM, AutoProcessor'),
            ('PIL', 'from PIL import Image'),
            ('fastapi', 'from fastapi import FastAPI'),
        ]
        
        import_results = {}
        
        for name, import_cmd in imports_to_test:
            start_time = time.time()
            try:
                exec(import_cmd)
                import_time = time.time() - start_time
                import_results[name] = {
                    'success': True,
                    'time': import_time
                }
                logger.info(f"✅ {name}: {import_time:.3f}s")
            except Exception as e:
                import_time = time.time() - start_time
                import_results[name] = {
                    'success': False,
                    'time': import_time,
                    'error': str(e)
                }
                logger.error(f"❌ {name}: {import_time:.3f}s (failed: {e})")
        
        self.results['benchmarks']['imports'] = import_results
        return import_results
    
    def save_results(self):
        """Save benchmark results to file"""
        try:
            # Save to a location that will be preserved in the Docker image
            results_dir = Path('/tmp/benchmark_results')
            results_dir.mkdir(exist_ok=True)
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            results_file = results_dir / f"build_benchmark_{timestamp}.json"
            
            with open(results_file, 'w') as f:
                json.dump(self.results, f, indent=2)
            
            logger.info(f"📄 Benchmark results saved to: {results_file}")
            
            # Also save a "latest" file for easy access
            latest_file = results_dir / "latest_build_benchmark.json"
            with open(latest_file, 'w') as f:
                json.dump(self.results, f, indent=2)
            
            logger.info(f"📄 Latest results saved to: {latest_file}")
            
            return results_file
            
        except Exception as e:
            logger.error(f"❌ Failed to save benchmark results: {e}")
            return None
    
    def print_summary(self):
        """Print a summary of benchmark results"""
        print("\n" + "="*60)
        print("🏆 BUILD-TIME BENCHMARK SUMMARY")
        print("="*60)
        
        # Environment info
        env = self.results['build_environment']
        print(f"🐍 Python: {env['python_version'].split()[0]}")
        
        if 'cuda_available' in env and env['cuda_available'].get('available'):
            cuda_info = env['cuda_available']
            print(f"🔥 CUDA: {cuda_info.get('version', 'Unknown')} ({cuda_info.get('device_count', 0)} devices)")
        
        if 'memory_info' in env and 'total_gb' in env['memory_info']:
            mem_info = env['memory_info']
            print(f"💾 Memory: {mem_info['available_gb']:.1f}GB available / {mem_info['total_gb']:.1f}GB total")
        
        if 'disk_space' in env and 'free_gb' in env['disk_space']:
            disk_info = env['disk_space']
            print(f"💿 Disk: {disk_info['free_gb']:.1f}GB free / {disk_info['total_gb']:.1f}GB total")
        
        # Benchmark results
        benchmarks = self.results['benchmarks']
        
        if 'model_warmup' in benchmarks:
            warmup = benchmarks['model_warmup']
            print(f"\n🔥 Model Warmup:")
            print(f"   Status: {'✅ Success' if warmup['success'] else '❌ Failed'}")
            if warmup['success']:
                print(f"   Total Time: {warmup['total_time']:.2f}s")
                print(f"   Model Time: {warmup.get('model_warmup_time', 0):.2f}s")
                print(f"   Cache Size: {warmup.get('final_cache_size_gb', 0):.2f}GB")
        
        if 'imports' in benchmarks:
            imports = benchmarks['imports']
            print(f"\n📦 Import Times:")
            for name, result in imports.items():
                status = "✅" if result['success'] else "❌"
                print(f"   {name}: {status} {result['time']:.3f}s")
        
        print("="*60)

def main():
    """Main benchmark execution for build time"""
    logger.info("🚀 Starting automated build-time benchmarking...")
    
    benchmark = BuildTimeBenchmark()
    
    try:
        # Run benchmarks
        benchmark.benchmark_import_times()
        benchmark.benchmark_model_warmup()
        
        # Save and display results
        results_file = benchmark.save_results()
        benchmark.print_summary()
        
        # Check if warmup was successful
        warmup_result = benchmark.results['benchmarks'].get('model_warmup', {})
        if not warmup_result.get('success', False):
            logger.error("❌ Model warmup failed - build should fail")
            sys.exit(1)
        
        logger.info("🎉 Build-time benchmarking completed successfully!")
        
    except Exception as e:
        logger.error(f"❌ Build-time benchmarking failed: {e}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        sys.exit(1)

if __name__ == "__main__":
    main()
