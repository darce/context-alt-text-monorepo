"""
Latency Benchmark Test

Benchmark the recognition service latency to ensure it meets performance requirements.
"""

import pytest
import time
import statistics
from PIL import Image
from typing import List

from recognition.services import RecognitionService


@pytest.fixture
def recognition_service():
    """Create recognition service instance."""
    return RecognitionService()


def create_test_images(count: int = 10) -> List[Image.Image]:
    """Create a set of test images for benchmarking."""
    images = []
    for i in range(count):
        # Create images of varying sizes to simulate real-world conditions
        size = 200 + (i * 50)  # 200x200 to 650x650
        color = (50 + i * 20, 100 + i * 10, 150 + i * 5)
        image = Image.new('RGB', (size, size), color=color)
        images.append(image)
    return images


@pytest.mark.asyncio
async def test_latency_single_image(recognition_service):
    """Test latency for a single image recognition."""
    test_image = Image.new('RGB', (300, 300), color=(128, 128, 128))
    
    # Warm up the model
    await recognition_service.recognize_faces(test_image)
    
    # Measure latency
    start_time = time.time()
    result = await recognition_service.recognize_faces(test_image)
    latency_ms = (time.time() - start_time) * 1000
    
    print(f"Single image latency: {latency_ms:.1f}ms")
    
    # Verify the result is valid
    assert result is not None
    assert result.processing_time_ms > 0
    
    # Basic latency check (should be reasonable)
    assert latency_ms < 5000, f"Latency too high: {latency_ms:.1f}ms"


@pytest.mark.asyncio
async def test_latency_multiple_images(recognition_service):
    """Test latency for multiple image recognitions."""
    test_images = create_test_images(5)
    latencies = []
    
    # Warm up
    await recognition_service.recognize_faces(test_images[0])
    
    # Measure latencies
    for i, image in enumerate(test_images):
        start_time = time.time()
        result = await recognition_service.recognize_faces(image)
        latency_ms = (time.time() - start_time) * 1000
        latencies.append(latency_ms)
        
        print(f"Image {i+1} latency: {latency_ms:.1f}ms")
        
        # Verify result
        assert result is not None
    
    # Calculate statistics
    avg_latency = statistics.mean(latencies)
    p95_latency = sorted(latencies)[int(0.95 * len(latencies))]
    
    print(f"Average latency: {avg_latency:.1f}ms")
    print(f"P95 latency: {p95_latency:.1f}ms")
    
    # Performance assertions
    assert avg_latency < 2000, f"Average latency too high: {avg_latency:.1f}ms"


@pytest.mark.asyncio
async def bench_latency_micro():
    """
    Main latency benchmark test.
    
    This test should ensure P95 latency < 1200ms on M1 CPU as specified
    in the requirements.
    """
    service = RecognitionService()
    
    # Create test images of different sizes
    test_images = [
        Image.new('RGB', (200, 200), color=(100, 100, 100)),
        Image.new('RGB', (400, 400), color=(150, 150, 150)),
        Image.new('RGB', (640, 640), color=(200, 200, 200)),
        Image.new('RGB', (800, 600), color=(120, 140, 160)),
        Image.new('RGB', (1024, 768), color=(180, 160, 140)),
    ]
    
    # Warm up the model (first inference is always slower)
    print("Warming up model...")
    await service.recognize_faces(test_images[0])
    
    # Run benchmark
    latencies = []
    total_faces_detected = 0
    
    print("Running latency benchmark...")
    for run in range(20):  # 20 runs for statistical significance
        for i, image in enumerate(test_images):
            start_time = time.time()
            
            try:
                result = await service.recognize_faces(image)
                latency_ms = (time.time() - start_time) * 1000
                latencies.append(latency_ms)
                total_faces_detected += len(result.face_detections)
                
                print(f"Run {run+1}, Image {i+1}: {latency_ms:.1f}ms, "
                      f"{len(result.face_detections)} faces")
                
            except Exception as e:
                print(f"Error in run {run+1}, image {i+1}: {e}")
                latencies.append(5000)  # Penalty for failures
    
    # Calculate statistics
    if latencies:
        avg_latency = statistics.mean(latencies)
        median_latency = statistics.median(latencies)
        p95_latency = sorted(latencies)[int(0.95 * len(latencies))]
        min_latency = min(latencies)
        max_latency = max(latencies)
        
        print("\n" + "="*50)
        print("LATENCY BENCHMARK RESULTS")
        print("="*50)
        print(f"Total test runs: {len(latencies)}")
        print(f"Total faces detected: {total_faces_detected}")
        print(f"Min latency:     {min_latency:.1f}ms")
        print(f"Avg latency:     {avg_latency:.1f}ms")
        print(f"Median latency:  {median_latency:.1f}ms")
        print(f"P95 latency:     {p95_latency:.1f}ms")
        print(f"Max latency:     {max_latency:.1f}ms")
        print("="*50)
        
        # Requirements check
        # P95 should be < 1200ms on M1 CPU (requirement from spec)
        assert p95_latency < 1200, f"P95 latency {p95_latency:.1f}ms exceeds 1200ms requirement"
        
        # Average should be reasonable
        assert avg_latency < 800, f"Average latency {avg_latency:.1f}ms is too high"
        
        # No individual request should take more than 5 seconds
        assert max_latency < 5000, f"Max latency {max_latency:.1f}ms is unacceptable"
        
        print("✅ All latency requirements met!")
        
        return {
            "avg_latency_ms": avg_latency,
            "p95_latency_ms": p95_latency,
            "median_latency_ms": median_latency,
            "total_runs": len(latencies),
            "total_faces_detected": total_faces_detected
        }
    else:
        pytest.fail("No latency measurements collected")


@pytest.mark.asyncio
async def test_concurrent_requests():
    """Test handling of concurrent recognition requests."""
    import asyncio
    
    service = RecognitionService()
    test_images = create_test_images(3)
    
    # Warm up
    await service.recognize_faces(test_images[0])
    
    async def recognize_image(image, image_id):
        start_time = time.time()
        result = await service.recognize_faces(image)
        latency = (time.time() - start_time) * 1000
        return image_id, latency, len(result.face_detections)
    
    # Run concurrent requests
    print("Testing concurrent requests...")
    start_time = time.time()
    
    tasks = [
        recognize_image(test_images[i % len(test_images)], i) 
        for i in range(6)  # 6 concurrent requests
    ]
    
    results = await asyncio.gather(*tasks)
    total_time = (time.time() - start_time) * 1000
    
    print(f"Processed {len(results)} concurrent requests in {total_time:.1f}ms")
    
    for image_id, latency, face_count in results:
        print(f"Request {image_id}: {latency:.1f}ms, {face_count} faces")
    
    # All requests should complete successfully
    assert len(results) == 6
    
    # Individual latencies should still be reasonable
    latencies = [r[1] for r in results]
    max_latency = max(latencies)
    assert max_latency < 3000, f"Concurrent request latency too high: {max_latency:.1f}ms"


if __name__ == "__main__":
    # Run the benchmark directly
    import asyncio
    
    async def main():
        print("Running latency benchmark...")
        results = await bench_latency_micro()
        print(f"Benchmark complete: {results}")
    
    asyncio.run(main())
