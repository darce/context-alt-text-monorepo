#!/usr/bin/env python3
"""
Warmup Performance Benchmark - Measures actual time savings from model pre-caching.

This script benchmarks the difference between cold start (no cache) and warm start 
(pre-cached models) to provide real performance metrics.
"""

import os
import time
import tempfile
import shutil
import json
from datetime import datetime
from pathlib import Path
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class WarmupBenchmark:
    """Benchmark warmup performance by comparing cold vs warm starts."""
    
    def __init__(self):
        self.results = {
            "timestamp": datetime.now().isoformat(),
            "cold_start_time": 0.0,
            "warm_start_time": 0.0,
            "time_saved": 0.0,
            "percentage_improvement": 0.0,
            "cache_size_gb": 0.0,
            "success": False
        }
    
    def benchmark_cold_start(self, temp_cache_dir: str) -> float:
        """Benchmark cold start (no cache) performance."""
        logger.info("❄️ Benchmarking COLD START (no cached models)...")
        
        # Ensure no cache exists
        if os.path.exists(temp_cache_dir):
            shutil.rmtree(temp_cache_dir)
        os.makedirs(temp_cache_dir, exist_ok=True)
        
        # Set environment to use temporary cache
        original_hf_home = os.environ.get('HF_HOME')
        os.environ['HF_HOME'] = temp_cache_dir
        os.environ['TRANSFORMERS_CACHE'] = temp_cache_dir + '/transformers'
        
        start_time = time.time()
        
        try:
            # Import and run warmup (this will download models)
            from shared.infrastructure.preload_model import download_model_files
            success = download_model_files()
            
            if not success:
                raise Exception("Warmup failed")
                
            cold_time = time.time() - start_time
            logger.info(f"✅ Cold start completed in {cold_time:.2f}s")
            
            return cold_time
            
        except Exception as e:
            logger.error(f"❌ Cold start failed: {e}")
            raise
        finally:
            # Restore original environment
            if original_hf_home:
                os.environ['HF_HOME'] = original_hf_home
            else:
                os.environ.pop('HF_HOME', None)
    
    def benchmark_warm_start(self, cache_dir: str) -> float:
        """Benchmark warm start (with cache) performance."""
        logger.info("🔥 Benchmarking WARM START (pre-cached models)...")
        
        # Verify cache exists and has content
        if not os.path.exists(cache_dir) or not os.listdir(cache_dir):
            raise Exception("Cache directory empty - cannot benchmark warm start")
        
        # Set environment to use existing cache
        original_hf_home = os.environ.get('HF_HOME')
        os.environ['HF_HOME'] = cache_dir
        os.environ['TRANSFORMERS_CACHE'] = cache_dir + '/transformers'
        
        start_time = time.time()
        
        try:
            # Import and run warmup (this should use cached models)
            from shared.infrastructure.preload_model import download_model_files
            success = download_model_files()
            
            if not success:
                raise Exception("Warm start failed")
                
            warm_time = time.time() - start_time
            logger.info(f"✅ Warm start completed in {warm_time:.2f}s")
            
            return warm_time
            
        except Exception as e:
            logger.error(f"❌ Warm start failed: {e}")
            raise
        finally:
            # Restore original environment
            if original_hf_home:
                os.environ['HF_HOME'] = original_hf_home
            else:
                os.environ.pop('HF_HOME', None)
    
    def calculate_cache_size(self, cache_dir: str) -> float:
        """Calculate cache directory size in GB."""
        if not os.path.exists(cache_dir):
            return 0.0
        
        total_size = 0
        for root, dirs, files in os.walk(cache_dir):
            for file in files:
                try:
                    total_size += os.path.getsize(os.path.join(root, file))
                except OSError:
                    pass
        
        return total_size / (1024**3)  # Convert to GB
    
    def run_benchmark(self) -> dict:
        """Run complete warmup benchmark."""
        logger.info("🚀 Starting Warmup Performance Benchmark...")
        
        # Create temporary directories
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_cache_dir = os.path.join(temp_dir, 'cold_cache')
            warm_cache_dir = os.path.join(temp_dir, 'warm_cache')
            
            try:
                # Step 1: Benchmark cold start
                cold_time = self.benchmark_cold_start(temp_cache_dir)
                self.results["cold_start_time"] = cold_time
                
                # Step 2: Copy cache for warm start test
                if os.path.exists(temp_cache_dir):
                    shutil.copytree(temp_cache_dir, warm_cache_dir)
                
                # Step 3: Benchmark warm start
                warm_time = self.benchmark_warm_start(warm_cache_dir)
                self.results["warm_start_time"] = warm_time
                
                # Step 4: Calculate metrics
                time_saved = cold_time - warm_time
                percentage_improvement = (time_saved / cold_time) * 100 if cold_time > 0 else 0
                cache_size = self.calculate_cache_size(warm_cache_dir)
                
                self.results.update({
                    "time_saved": time_saved,
                    "percentage_improvement": percentage_improvement,
                    "cache_size_gb": cache_size,
                    "success": True
                })
                
                # Log results
                logger.info("📊 BENCHMARK RESULTS:")
                logger.info(f"   Cold start: {cold_time:.2f}s")
                logger.info(f"   Warm start: {warm_time:.2f}s")
                logger.info(f"   Time saved: {time_saved:.2f}s")
                logger.info(f"   Improvement: {percentage_improvement:.1f}%")
                logger.info(f"   Cache size: {cache_size:.2f}GB")
                
                return self.results
                
            except Exception as e:
                logger.error(f"❌ Benchmark failed: {e}")
                self.results["success"] = False
                self.results["error"] = str(e)
                return self.results
    
    def save_results(self, file_path: str = None) -> str:
        """Save benchmark results to file."""
        if file_path is None:
            file_path = "/tmp/warmup_benchmark_results.json"
        
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        
        with open(file_path, 'w') as f:
            json.dump(self.results, f, indent=2)
        
        logger.info(f"📁 Results saved to: {file_path}")
        return file_path

def get_cached_benchmark_results() -> dict:
    """Get previously cached benchmark results if available."""
    cache_file = "/tmp/warmup_benchmark_results.json"
    
    if os.path.exists(cache_file):
        try:
            with open(cache_file, 'r') as f:
                results = json.load(f)
            
            # Check if results are recent (within 24 hours)
            timestamp = datetime.fromisoformat(results.get("timestamp", ""))
            age_hours = (datetime.now() - timestamp).total_seconds() / 3600
            
            if age_hours < 24 and results.get("success", False):
                logger.info(f"📋 Using cached benchmark results ({age_hours:.1f}h old)")
                return results
        except Exception as e:
            logger.warning(f"⚠️ Could not load cached results: {e}")
    
    return None

def main():
    """Run warmup benchmark if not cached."""
    # Try to get cached results first
    cached_results = get_cached_benchmark_results()
    if cached_results:
        return cached_results
    
    # Run new benchmark
    benchmark = WarmupBenchmark()
    results = benchmark.run_benchmark()
    benchmark.save_results()
    
    return results

if __name__ == "__main__":
    results = main()
    print("\n" + "="*50)
    print("🎯 WARMUP PERFORMANCE SUMMARY")
    print("="*50)
    
    if results.get("success"):
        print(f"Cold Start Time: {results['cold_start_time']:.2f}s")
        print(f"Warm Start Time: {results['warm_start_time']:.2f}s")
        print(f"Time Saved: {results['time_saved']:.2f}s")
        print(f"Performance Improvement: {results['percentage_improvement']:.1f}%")
        print(f"Cache Size: {results['cache_size_gb']:.2f}GB")
    else:
        print(f"❌ Benchmark failed: {results.get('error', 'Unknown error')}")
