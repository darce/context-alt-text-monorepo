#!/usr/bin/env python3
"""
Recognition Service Benchmark
Simple benchmark script for testing latency and accuracy.
"""
import asyncio
import time
import logging
from pathlib import Path
from typing import List, Dict, Any
import numpy as np
from PIL import Image
import argparse

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def benchmark_latency(recognition_service, test_images: List[Image.Image], 
                          model_type: str, threshold: float, iterations: int = 10) -> Dict[str, float]:
    """
    Benchmark latency for a model.
    
    Args:
        recognition_service: Recognition service instance
        test_images: List of test images
        model_type: Model type to test
        threshold: Recognition threshold
        iterations: Number of iterations
        
    Returns:
        Latency statistics
    """
    from recognition.domain import ModelType
    
    model_enum = ModelType(model_type)
    latencies = []
    
    logger.info(f"🏃 Benchmarking {model_type} with {len(test_images)} images, {iterations} iterations")
    
    for i in range(iterations):
        for image in test_images:
            start_time = time.time()
            
            try:
                result = await recognition_service.analyze_scene(
                    image=image,
                    model_type=model_enum,
                    threshold=threshold
                )
                latency = (time.time() - start_time) * 1000  # Convert to ms
                latencies.append(latency)
                
                logger.debug(f"Iteration {i+1}: {latency:.2f}ms, {result.total_faces} faces")
                
            except Exception as e:
                logger.error(f"Error in iteration {i+1}: {e}")
                continue
    
    if not latencies:
        return {"error": "No successful iterations"}
    
    # Calculate statistics
    latencies = np.array(latencies)
    stats = {
        "mean": float(np.mean(latencies)),
        "median": float(np.median(latencies)),
        "p95": float(np.percentile(latencies, 95)),
        "p99": float(np.percentile(latencies, 99)),
        "min": float(np.min(latencies)),
        "max": float(np.max(latencies)),
        "std": float(np.std(latencies)),
        "iterations": len(latencies)
    }
    
    logger.info(f"📊 {model_type} latency stats: "
                f"mean={stats['mean']:.2f}ms, "
                f"p95={stats['p95']:.2f}ms, "
                f"p99={stats['p99']:.2f}ms")
    
    return stats


def create_test_images(num_images: int = 5) -> List[Image.Image]:
    """
    Create test images for benchmarking.
    
    Args:
        num_images: Number of test images to create
        
    Returns:
        List of test images
    """
    images = []
    
    for i in range(num_images):
        # Create random RGB image
        image_array = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)
        image = Image.fromarray(image_array)
        images.append(image)
    
    logger.info(f"🖼️ Created {num_images} test images")
    return images


def load_test_images(image_dir: str) -> List[Image.Image]:
    """
    Load test images from directory.
    
    Args:
        image_dir: Directory containing test images
        
    Returns:
        List of loaded images
    """
    image_path = Path(image_dir)
    if not image_path.exists():
        logger.warning(f"Image directory not found: {image_dir}")
        return create_test_images()
    
    images = []
    for ext in ['*.jpg', '*.jpeg', '*.png', '*.bmp']:
        for img_file in image_path.glob(ext):
            try:
                image = Image.open(img_file).convert('RGB')
                images.append(image)
                logger.debug(f"Loaded image: {img_file}")
            except Exception as e:
                logger.error(f"Failed to load image {img_file}: {e}")
    
    if not images:
        logger.warning("No images found, creating synthetic test images")
        return create_test_images()
    
    logger.info(f"📁 Loaded {len(images)} test images from {image_dir}")
    return images


async def run_benchmark(args):
    """Run the benchmark."""
    try:
        # Import recognition service
        from recognition.ports.dependencies import get_recognition_service
        
        # Get service
        recognition_service = get_recognition_service()
        
        # Load test images
        if args.image_dir:
            test_images = load_test_images(args.image_dir)
        else:
            test_images = create_test_images(args.num_images)
        
        # Models to test
        models = args.models.split(',') if args.models else ['adaface_ir101', 'insightface_w600k', 'arcface_ir50']
        
        results = {}
        
        for model_type in models:
            logger.info(f"🧪 Testing model: {model_type}")
            
            try:
                stats = await benchmark_latency(
                    recognition_service=recognition_service,
                    test_images=test_images,
                    model_type=model_type,
                    threshold=args.threshold,
                    iterations=args.iterations
                )
                
                results[model_type] = stats
                
            except Exception as e:
                logger.error(f"❌ Failed to benchmark {model_type}: {e}")
                results[model_type] = {"error": str(e)}
        
        # Print results
        print("\n" + "="*60)
        print("BENCHMARK RESULTS")
        print("="*60)
        
        for model_type, stats in results.items():
            print(f"\n{model_type.upper()}:")
            if "error" in stats:
                print(f"  ❌ Error: {stats['error']}")
            else:
                print(f"  📊 Mean latency: {stats['mean']:.2f}ms")
                print(f"  📈 P95 latency: {stats['p95']:.2f}ms")
                print(f"  📉 P99 latency: {stats['p99']:.2f}ms")
                print(f"  🎯 Min latency: {stats['min']:.2f}ms")
                print(f"  🚀 Max latency: {stats['max']:.2f}ms")
                print(f"  📏 Std deviation: {stats['std']:.2f}ms")
                print(f"  🔢 Iterations: {stats['iterations']}")
                
                # Performance evaluation
                target_p95 = 600 if args.device == 'cpu' else 150
                if stats['p95'] <= target_p95:
                    print(f"  ✅ PASS: P95 {stats['p95']:.2f}ms <= {target_p95}ms")
                else:
                    print(f"  ❌ FAIL: P95 {stats['p95']:.2f}ms > {target_p95}ms")
        
        print("\n" + "="*60)
        
    except Exception as e:
        logger.error(f"Benchmark failed: {e}")
        raise


def main():
    """Main function."""
    parser = argparse.ArgumentParser(description="Recognition Service Benchmark")
    parser.add_argument("--models", type=str, default="adaface_ir101,insightface_w600k,arcface_ir50",
                       help="Comma-separated list of models to test")
    parser.add_argument("--threshold", type=float, default=0.5,
                       help="Recognition threshold")
    parser.add_argument("--iterations", type=int, default=10,
                       help="Number of iterations per model")
    parser.add_argument("--num-images", type=int, default=5,
                       help="Number of synthetic test images")
    parser.add_argument("--image-dir", type=str, default=None,
                       help="Directory containing test images")
    parser.add_argument("--device", type=str, default="auto",
                       help="Device to use (cpu, cuda, mps, auto)")
    
    args = parser.parse_args()
    
    # Run benchmark
    asyncio.run(run_benchmark(args))


if __name__ == "__main__":
    main()
