#!/usr/bin/env python3
"""
Attention Optimization Benchmarker

This module provides benchmarking capabilities to measure actual performance
improvements from different attention optimization strategies. It replaces
hardcoded estimates with real measurements.
"""

import time
import torch
import logging
import statistics
from typing import Dict, Any, List, Tuple, Optional
from dataclasses import dataclass
from contextlib import contextmanager

from shared.infrastructure.ports.attention_optimizer_base import IAttentionOptimizer
from shared.enums.attention_backend import AttentionBackend

logger = logging.getLogger(__name__)


@dataclass
class BenchmarkResult:
    """Results from attention optimization benchmarking."""
    backend: AttentionBackend
    device: str
    avg_time_ms: float
    std_dev_ms: float
    min_time_ms: float
    max_time_ms: float
    iterations: int
    speedup_vs_eager: float = 1.0
    memory_usage_mb: Optional[float] = None
    success: bool = True
    error_message: Optional[str] = None


class AttentionBenchmarker:
    """
    Benchmarks attention optimization strategies to measure real performance.
    
    This class creates standardized test scenarios and measures actual
    performance improvements instead of relying on hardcoded estimates.
    """
    
    def __init__(self, device: str = "auto", warmup_iterations: int = 5, 
        benchmark_iterations: int = 20):
        self.device = device if device != "auto" else self._detect_device()
        self.warmup_iterations = warmup_iterations
        self.benchmark_iterations = benchmark_iterations
        self.eager_baseline: Optional[float] = None
        
        # Standard test configurations
        self.test_configs = [
            # Small model test (fast)
            {
                "name": "small",
                "batch_size": 1,
                "seq_len": 128,
                "d_model": 256,
                "nhead": 4
            },
            # Medium model test (realistic)
            {
                "name": "medium", 
                "batch_size": 2,
                "seq_len": 512,
                "d_model": 768,
                "nhead": 12
            },
            # Large model test (stress test)
            {
                "name": "large",
                "batch_size": 1,
                "seq_len": 1024,
                "d_model": 1024,
                "nhead": 16
            }
        ]
    
    def _detect_device(self) -> str:
        """Detect the best available device."""
        if torch.cuda.is_available():
            return "cuda"
        elif hasattr(torch.backends, 'mps') and torch.backends.mps.is_available():
            return "mps"
        else:
            return "cpu"
    
    def _create_test_model(self, config: Dict[str, Any]) -> torch.nn.Module:
        """Create a test model for benchmarking."""
        class AttentionTestModel(torch.nn.Module):
            def __init__(self, d_model: int, nhead: int):
                super().__init__()
                self.multihead_attn = torch.nn.MultiheadAttention(
                    d_model, nhead, batch_first=True
                )
                self.norm = torch.nn.LayerNorm(d_model)
                
            def forward(self, x):
                # Self-attention with residual connection
                attn_output, _ = self.multihead_attn(x, x, x)
                return self.norm(x + attn_output)
        
        model = AttentionTestModel(config["d_model"], config["nhead"])
        return model.to(self.device).eval()
    
    def _create_test_input(self, config: Dict[str, Any]) -> torch.Tensor:
        """Create test input tensor."""
        return torch.randn(
            config["batch_size"], 
            config["seq_len"], 
            config["d_model"],
            device=self.device
        )
    
    def _get_memory_usage(self) -> Optional[float]:
        """Get current memory usage in MB."""
        try:
            if self.device == "cuda":
                return torch.cuda.memory_allocated() / (1024 * 1024)
            elif self.device == "mps":
                return torch.mps.current_allocated_memory() / (1024 * 1024)
            else:
                # CPU memory is harder to measure accurately
                return None
        except Exception:
            return None
    
    @contextmanager
    def _memory_monitor(self):
        """Context manager to monitor memory usage."""
        initial_memory = self._get_memory_usage()
        yield
        final_memory = self._get_memory_usage()
        
        if initial_memory is not None and final_memory is not None:
            self.last_memory_usage = final_memory - initial_memory
        else:
            self.last_memory_usage = None
    
    def benchmark_optimizer(self, optimizer: IAttentionOptimizer, test_config: str = "medium") -> BenchmarkResult:
        """
        Benchmark a specific attention optimizer.
        
        Args:
            optimizer: The attention optimizer to benchmark
            test_config: Test configuration name ("small", "medium", "large")
            
        Returns:
            BenchmarkResult with actual measured performance
        """
        # Get test configuration
        config = next((c for c in self.test_configs if c["name"] == test_config), self.test_configs[1])  # Default to medium
        
        logger.info(f"Benchmarking {optimizer.backend_type.value} on {self.device} "f"with {config['name']} config")
        
        try:
            # Check if optimizer is available
            if not optimizer.is_available(self.device):
                return BenchmarkResult(
                    backend=optimizer.backend_type,
                    device=self.device,
                    avg_time_ms=float('inf'),
                    std_dev_ms=0.0,
                    min_time_ms=float('inf'),
                    max_time_ms=float('inf'),
                    iterations=0,
                    success=False,
                    error_message=f"Optimizer not available on {self.device}"
                )
            
            # Create test model and input
            model = self._create_test_model(config)
            test_input = self._create_test_input(config)
            
            # Apply optimizer's runtime optimizations
            model = optimizer.apply_runtime_optimizations(model, self.device)
            
            # Warmup
            with torch.no_grad():
                with optimizer.get_context_manager(self.device):
                    for _ in range(self.warmup_iterations):
                        _ = model(test_input)
            
            # Clear cache if CUDA
            if self.device == "cuda":
                torch.cuda.empty_cache()
                torch.cuda.synchronize()
            elif self.device == "mps":
                torch.mps.empty_cache()
                torch.mps.synchronize()
            
            # Benchmark
            times = []
            with torch.no_grad():
                with self._memory_monitor():
                    with optimizer.get_context_manager(self.device):
                        for _ in range(self.benchmark_iterations):
                            start_time = time.perf_counter()
                            
                            output = model(test_input)
                            
                            # Ensure computation is complete
                            if self.device == "cuda":
                                torch.cuda.synchronize()
                            elif self.device == "mps":
                                torch.mps.synchronize()
                            
                            end_time = time.perf_counter()
                            times.append((end_time - start_time) * 1000)  # Convert to ms
            
            # Calculate statistics
            avg_time = statistics.mean(times)
            std_dev = statistics.stdev(times) if len(times) > 1 else 0.0
            min_time = min(times)
            max_time = max(times)
            
            # Calculate speedup vs eager baseline
            speedup = 1.0
            if self.eager_baseline is not None:
                speedup = self.eager_baseline / avg_time
            
            result = BenchmarkResult(
                backend=optimizer.backend_type,
                device=self.device,
                avg_time_ms=avg_time,
                std_dev_ms=std_dev,
                min_time_ms=min_time,
                max_time_ms=max_time,
                iterations=self.benchmark_iterations,
                speedup_vs_eager=speedup,
                memory_usage_mb=getattr(self, 'last_memory_usage', None),
                success=True
            )
            
            logger.info(f"Benchmark complete: {optimizer.backend_type.value} "f"avg={avg_time:.2f}ms, speedup={speedup:.2f}x")
            
            return result
            
        except Exception as e:
            logger.error(f"Benchmark failed for {optimizer.backend_type.value}: {e}")
            return BenchmarkResult(
                backend=optimizer.backend_type,
                device=self.device,
                avg_time_ms=float('inf'),
                std_dev_ms=0.0,
                min_time_ms=float('inf'),
                max_time_ms=float('inf'),
                iterations=0,
                success=False,
                error_message=str(e)
            )
    
    def benchmark_all_optimizers(self, optimizers: List[IAttentionOptimizer],
                                test_config: str = "medium") -> Dict[AttentionBackend, BenchmarkResult]:
        """
        Benchmark all provided optimizers and establish baseline.
        
        Args:
            optimizers: List of optimizers to benchmark
            test_config: Test configuration to use
            
        Returns:
            Dictionary mapping backend to benchmark results
        """
        results = {}
        
        # Find eager optimizer for baseline
        eager_optimizer = None
        for optimizer in optimizers:
            if optimizer.backend_type == AttentionBackend.EAGER:
                eager_optimizer = optimizer
                break
        
        # Benchmark eager first to establish baseline
        if eager_optimizer:
            logger.info("Establishing eager attention baseline...")
            eager_result = self.benchmark_optimizer(eager_optimizer, test_config)
            if eager_result.success:
                self.eager_baseline = eager_result.avg_time_ms
                logger.info(f"Eager baseline: {self.eager_baseline:.2f}ms")
            results[AttentionBackend.EAGER] = eager_result
        
        # Benchmark other optimizers
        for optimizer in optimizers:
            if optimizer.backend_type != AttentionBackend.EAGER:
                result = self.benchmark_optimizer(optimizer, test_config)
                results[optimizer.backend_type] = result
        
        return results
    
    def print_benchmark_summary(self, results: Dict[AttentionBackend, BenchmarkResult]):
        """Print a formatted summary of benchmark results."""
        print("\n📊 Attention Optimization Benchmark Results")
        print("=" * 70)
        print(f"Device: {self.device}")
        print(f"Iterations: {self.benchmark_iterations}")
        print()
        
        # Sort by average time (faster first)
        sorted_results = sorted(
            [(backend, result) for backend, result in results.items() if result.success],
            key=lambda x: x[1].avg_time_ms
        )
        
        print(f"{'Backend':<20} {'Avg Time (ms)':<15} {'Speedup':<10} {'Memory (MB)':<12} {'Status'}")
        print("-" * 70)
        
        for backend, result in sorted_results:
            memory_str = f"{result.memory_usage_mb:.1f}" if result.memory_usage_mb else "N/A"
            print(f"{backend.value:<20} {result.avg_time_ms:<15.2f} "f"{result.speedup_vs_eager:<10.2f} {memory_str:<12} ✅")
        
        # Show failed optimizers
        failed_results = [(backend, result) for backend, result in results.items() if not result.success]
        for backend, result in failed_results:
            print(f"{backend.value:<20} {'Failed':<15} {'N/A':<10} {'N/A':<12} ❌")
        
        print()
        
        # Show best performer
        if sorted_results:
            best_backend, best_result = sorted_results[0]
            print(f"🏆 Best performer: {best_backend.value} "f"({best_result.avg_time_ms:.2f}ms, {best_result.speedup_vs_eager:.2f}x speedup)")
    
    def quick_benchmark(self, optimizers: List[IAttentionOptimizer]) -> Dict[AttentionBackend, float]:
        """
        Quick benchmark returning just speedup ratios.
        
        Args:
            optimizers: List of optimizers to benchmark
            
        Returns:
            Dictionary mapping backend to speedup ratio
        """
        # Use small config for quick benchmark
        results = self.benchmark_all_optimizers(optimizers, "small")
        
        speedups = {}
        for backend, result in results.items():
            if result.success:
                speedups[backend] = result.speedup_vs_eager
            else:
                speedups[backend] = 1.0  # No improvement if failed
        
        return speedups


def benchmark_attention_optimizations(optimizers: List[IAttentionOptimizer],
    device: str = "auto", 
    test_config: str = "medium") -> Dict[AttentionBackend, float]:
    """
    Convenience function to benchmark provided attention optimizations.
    
    Args:
        optimizers: List of attention optimizers to benchmark
        device: Device to benchmark on
        test_config: Test configuration ("small", "medium", "large")
        
    Returns:
        Dictionary mapping backend to actual measured speedup ratios
    """
    benchmarker = AttentionBenchmarker(device)
    
    # Benchmark
    results = benchmarker.benchmark_all_optimizers(optimizers, test_config)
    
    # Print summary
    benchmarker.print_benchmark_summary(results)
    
    # Return speedup ratios
    speedups = {}
    for backend, result in results.items():
        speedups[backend] = result.speedup_vs_eager if result.success else 1.0
    
    return speedups
