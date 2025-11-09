"""
Tests for clustering configuration.

Validates YAML settings loading and environment variable overrides.
"""

import pytest
import os
from unittest import mock

from shared.config.settings import get_clustering_config


class TestClusteringConfig:
    """Test suite for clustering configuration"""
    
    def test_default_config(self):
        """Should load default values from YAML."""
        config = get_clustering_config()
        
        assert 'algorithm' in config
        assert 'distance_threshold' in config
        assert 'min_samples' in config
        assert 'linkage' in config
        
        # Defaults from settings.yaml
        assert config['algorithm'] == 'dbscan'
        assert config['distance_threshold'] == 0.6
        assert config['min_samples'] == 2
        assert config['linkage'] == 'average'
    
    def test_env_algorithm_override(self):
        """Should override algorithm from environment variable."""
        with mock.patch.dict(os.environ, {'CLUSTER_ALGORITHM': 'agglomerative'}):
            config = get_clustering_config()
            assert config['algorithm'] == 'agglomerative'
    
    def test_env_threshold_override(self):
        """Should override threshold from environment variable."""
        with mock.patch.dict(os.environ, {'CLUSTER_THRESHOLD': '0.75'}):
            config = get_clustering_config()
            assert config['distance_threshold'] == 0.75
    
    def test_env_min_samples_override(self):
        """Should override min_samples from environment variable."""
        with mock.patch.dict(os.environ, {'CLUSTER_MIN_SAMPLES': '3'}):
            config = get_clustering_config()
            assert config['min_samples'] == 3
    
    def test_env_linkage_override(self):
        """Should override linkage from environment variable."""
        with mock.patch.dict(os.environ, {'CLUSTER_LINKAGE': 'complete'}):
            config = get_clustering_config()
            assert config['linkage'] == 'complete'
    
    def test_all_env_overrides(self):
        """Should apply all environment variable overrides together."""
        env_vars = {
            'CLUSTER_ALGORITHM': 'agglomerative',
            'CLUSTER_THRESHOLD': '0.5',
            'CLUSTER_MIN_SAMPLES': '4',
            'CLUSTER_LINKAGE': 'single',
        }
        
        with mock.patch.dict(os.environ, env_vars):
            config = get_clustering_config()
            
            assert config['algorithm'] == 'agglomerative'
            assert config['distance_threshold'] == 0.5
            assert config['min_samples'] == 4
            assert config['linkage'] == 'single'
    
    def test_invalid_algorithm(self):
        """Should raise error for invalid algorithm."""
        with mock.patch.dict(os.environ, {'CLUSTER_ALGORITHM': 'invalid'}):
            with pytest.raises(ValueError, match="Invalid CLUSTER_ALGORITHM"):
                get_clustering_config()
    
    def test_invalid_threshold_range(self):
        """Should raise error for threshold outside valid range."""
        with mock.patch.dict(os.environ, {'CLUSTER_THRESHOLD': '3.0'}):
            with pytest.raises(ValueError, match="Invalid CLUSTER_THRESHOLD"):
                get_clustering_config()
    
    def test_invalid_threshold_type(self):
        """Should raise error for non-numeric threshold."""
        with mock.patch.dict(os.environ, {'CLUSTER_THRESHOLD': 'not_a_number'}):
            with pytest.raises(ValueError, match="Invalid CLUSTER_THRESHOLD"):
                get_clustering_config()
    
    def test_invalid_min_samples_range(self):
        """Should raise error for min_samples outside valid range."""
        with mock.patch.dict(os.environ, {'CLUSTER_MIN_SAMPLES': '15'}):
            with pytest.raises(ValueError, match="Invalid CLUSTER_MIN_SAMPLES"):
                get_clustering_config()
    
    def test_invalid_min_samples_type(self):
        """Should raise error for non-integer min_samples."""
        with mock.patch.dict(os.environ, {'CLUSTER_MIN_SAMPLES': '2.5'}):
            with pytest.raises(ValueError, match="Invalid CLUSTER_MIN_SAMPLES"):
                get_clustering_config()
    
    def test_invalid_linkage(self):
        """Should raise error for invalid linkage method."""
        with mock.patch.dict(os.environ, {'CLUSTER_LINKAGE': 'invalid_method'}):
            with pytest.raises(ValueError, match="Invalid CLUSTER_LINKAGE"):
                get_clustering_config()
    
    def test_threshold_boundary_values(self):
        """Should accept threshold at boundary values."""
        # Test minimum boundary
        with mock.patch.dict(os.environ, {'CLUSTER_THRESHOLD': '0.0'}):
            config = get_clustering_config()
            assert config['distance_threshold'] == 0.0
        
        # Test maximum boundary
        with mock.patch.dict(os.environ, {'CLUSTER_THRESHOLD': '2.0'}):
            config = get_clustering_config()
            assert config['distance_threshold'] == 2.0
    
    def test_min_samples_boundary_values(self):
        """Should accept min_samples at boundary values."""
        # Test minimum boundary
        with mock.patch.dict(os.environ, {'CLUSTER_MIN_SAMPLES': '1'}):
            config = get_clustering_config()
            assert config['min_samples'] == 1
        
        # Test maximum boundary
        with mock.patch.dict(os.environ, {'CLUSTER_MIN_SAMPLES': '10'}):
            config = get_clustering_config()
            assert config['min_samples'] == 10
