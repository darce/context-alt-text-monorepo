"""
Data Validation Adapter

Implements data validation for roster entries and bulk imports.
Provides comprehensive validation rules and error reporting.
"""

import logging
from typing import List, Dict, Any
import numpy as np

from ..domain.interfaces import DataValidationPort
from ..config import get_config

logger = logging.getLogger(__name__)


class DataValidationAdapter(DataValidationPort):
    """
    Data validation adapter with comprehensive validation rules.
    
    Validates:
    - Roster entry structure and content
    - Embedding dimensions and values
    - Bulk import data integrity
    """
    
    def __init__(self):
        """Initialize data validation adapter."""
        self.config = get_config()
        self.validation_config = self.config.get_validation_config()
    
    def validate_roster_entry(self, entry_data: Dict[str, Any]) -> List[str]:
        """
        Validate roster entry data.
        
        Args:
            entry_data: Raw entry data to validate
            
        Returns:
            List of validation errors (empty if valid)
        """
        errors = []
        
        try:
            # Check required fields (adjusted for RosterEntry structure)
            required_fields = self.validation_config.get("required_fields", ["name"])
            for field in required_fields:
                if field not in entry_data or entry_data[field] is None:
                    errors.append(f"Missing required field: {field}")
            
            # Special validation for embeddings (either aggregate or reference images with embeddings)
            has_aggregate = entry_data.get("aggregate_embedding") is not None
            has_reference_images = entry_data.get("reference_images") and len(entry_data["reference_images"]) > 0
            
            if not has_aggregate and not has_reference_images:
                errors.append("Entry must have either aggregate_embedding or reference_images with embeddings")
            
            # Validate name
            if "name" in entry_data:
                name = entry_data["name"]
                if not isinstance(name, str) or not name.strip():
                    errors.append("Name must be a non-empty string")
                elif len(name.strip()) > 255:
                    errors.append("Name must be 255 characters or less")
            
            # Validate display_name if provided
            if "display_name" in entry_data:
                display_name = entry_data["display_name"]
                if display_name is not None:
                    if not isinstance(display_name, str):
                        errors.append("Display name must be a string")
                    elif len(display_name) > 255:
                        errors.append("Display name must be 255 characters or less")
            
            # Validate unique_id if provided
            if "unique_id" in entry_data:
                unique_id = entry_data["unique_id"]
                if unique_id is not None:
                    if not isinstance(unique_id, str):
                        errors.append("Unique ID must be a string")
                    elif len(unique_id) > 128:
                        errors.append("Unique ID must be 128 characters or less")
            
            # Validate metadata if provided
            if "metadata" in entry_data:
                metadata = entry_data["metadata"]
                if metadata is not None:
                    if not isinstance(metadata, dict):
                        errors.append("Metadata must be a dictionary")
                    else:
                        # Check metadata size (prevent huge metadata objects)
                        if len(str(metadata)) > 10000:
                            errors.append("Metadata is too large (max 10KB)")
            
            # Validate reference_images if provided
            if "reference_images" in entry_data:
                ref_images = entry_data["reference_images"]
                if ref_images is not None:
                    if not isinstance(ref_images, list):
                        errors.append("Reference images must be a list")
                    else:
                        max_images = self.validation_config.get("max_entries_per_identity", 10)
                        if len(ref_images) > max_images:
                            errors.append(f"Too many reference images (max {max_images})")
                        
                        # Validate each reference image
                        for i, ref_img in enumerate(ref_images):
                            if not isinstance(ref_img, dict):
                                errors.append(f"Reference image {i} must be a dictionary")
                                continue
                            
                            if "embedding" not in ref_img:
                                errors.append(f"Reference image {i} missing embedding")
            
            # Validate timestamps if provided
            for ts_field in ["created_timestamp", "updated_timestamp"]:
                if ts_field in entry_data and entry_data[ts_field] is not None:
                    timestamp = entry_data[ts_field]
                    if not isinstance(timestamp, str):
                        errors.append(f"{ts_field} must be a string")
                    # Could add ISO format validation here if needed
            
        except Exception as e:
            errors.append(f"Validation error: {str(e)}")
        
        return errors
    
    def validate_embedding(self, embedding: List[float], model: str) -> List[str]:
        """
        Validate embedding data for a specific model.
        
        Args:
            embedding: Embedding vector to validate
            model: Model identifier for dimension checking
            
        Returns:
            List of validation errors (empty if valid)
        """
        errors = []
        
        try:
            # Check if embedding is a list
            if not isinstance(embedding, list):
                errors.append("Embedding must be a list of numbers")
                return errors
            
            # Check if embedding is empty
            if len(embedding) == 0:
                errors.append("Embedding cannot be empty")
                return errors
            
            # Check dimension
            expected_dim = self.config.get_embedding_dimension(model)
            if len(embedding) != expected_dim:
                errors.append(f"Embedding dimension mismatch: expected {expected_dim}, got {len(embedding)}")
            
            # Validate embedding config
            embedding_config = self.validation_config.get("embedding", {})
            min_dim = embedding_config.get("min_dimension", 64)
            max_dim = embedding_config.get("max_dimension", 2048)
            
            if len(embedding) < min_dim:
                errors.append(f"Embedding dimension too small: minimum {min_dim}")
            if len(embedding) > max_dim:
                errors.append(f"Embedding dimension too large: maximum {max_dim}")
            
            # Check if all values are numbers
            for i, value in enumerate(embedding):
                if not isinstance(value, (int, float)):
                    errors.append(f"Embedding value at index {i} is not a number")
                    continue
                
                # Check for NaN or infinity
                if np.isnan(value) or np.isinf(value):
                    errors.append(f"Embedding contains invalid value at index {i}: {value}")
            
            # Check for zero vector (if not allowed)
            if not embedding_config.get("allow_zero_vectors", False):
                if all(abs(x) < 1e-10 for x in embedding):
                    errors.append("Zero embedding vectors are not allowed")
            
            # Check embedding magnitude (detect unusual embeddings)
            magnitude = np.linalg.norm(embedding)
            if magnitude < 1e-6:
                errors.append("Embedding magnitude is suspiciously small")
            elif magnitude > 1000:
                errors.append("Embedding magnitude is suspiciously large")
        
        except Exception as e:
            errors.append(f"Embedding validation error: {str(e)}")
        
        return errors
    
    def validate_bulk_import(self, import_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Validate bulk import data.
        
        Args:
            import_data: List of entries to validate
            
        Returns:
            Validation result with errors and warnings
        """
        result = {
            "valid": True,
            "errors": [],
            "warnings": [],
            "entry_errors": {},  # Per-entry error tracking
            "stats": {
                "total_entries": len(import_data),
                "valid_entries": 0,
                "invalid_entries": 0
            }
        }
        
        try:
            # Check bulk size limit
            max_bulk_size = self.validation_config.get("max_bulk_import_size", 1000)
            if len(import_data) > max_bulk_size:
                result["errors"].append(f"Bulk import too large: {len(import_data)} entries (max {max_bulk_size})")
                result["valid"] = False
                return result
            
            # Check if data is a list
            if not isinstance(import_data, list):
                result["errors"].append("Import data must be a list of entries")
                result["valid"] = False
                return result
            
            # Validate each entry
            names_seen = set()
            for i, entry_data in enumerate(import_data):
                entry_errors = []
                
                # Basic structure validation
                if not isinstance(entry_data, dict):
                    entry_errors.append("Entry must be a dictionary")
                else:
                    # Validate the entry
                    validation_errors = self.validate_roster_entry(entry_data)
                    entry_errors.extend(validation_errors)
                    
                    # Check for duplicate names within the import
                    name = entry_data.get("name")
                    if name:
                        if name in names_seen:
                            entry_errors.append(f"Duplicate name in import: {name}")
                        else:
                            names_seen.add(name)
                
                # Track per-entry errors
                if entry_errors:
                    result["entry_errors"][i] = entry_errors
                    result["stats"]["invalid_entries"] += 1
                else:
                    result["stats"]["valid_entries"] += 1
            
            # Generate warnings for common issues
            if result["stats"]["invalid_entries"] > 0:
                invalid_pct = (result["stats"]["invalid_entries"] / result["stats"]["total_entries"]) * 100
                if invalid_pct > 50:
                    result["warnings"].append(f"High error rate: {invalid_pct:.1f}% of entries have validation errors")
            
            # Set overall validity
            if result["stats"]["invalid_entries"] > 0:
                result["valid"] = False
                result["errors"].append(f"{result['stats']['invalid_entries']} entries have validation errors")
        
        except Exception as e:
            result["errors"].append(f"Bulk validation error: {str(e)}")
            result["valid"] = False
        
        return result
    
    def validate_model_compatibility(self, model: str) -> List[str]:
        """
        Validate if a model is supported.
        
        Args:
            model: Model identifier
            
        Returns:
            List of validation errors (empty if valid)
        """
        errors = []
        
        supported_models = self.config.get_supported_models()
        if model not in supported_models:
            errors.append(f"Unsupported model: {model}. Supported models: {', '.join(supported_models)}")
        
        return errors
