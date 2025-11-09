"""Unit tests for PostgreSQL storage adapter metrics and logging."""

import time
from unittest.mock import MagicMock, patch

import pytest

from roster.adapters.postgresql_storage_adapter import DatabaseMetrics, PostgreSQLStorageAdapter
from roster.adapters import postgresql_storage_adapter as adapter_module


class TestDatabaseMetrics:
    """Test the DatabaseMetrics class."""
    
    def test_metrics_initialization(self):
        """Test metrics start at zero."""
        metrics = DatabaseMetrics()

        snapshot = metrics.snapshot()
        assert snapshot['query_count'] == 0
        assert snapshot['slow_query_count'] == 0
        assert snapshot['error_count'] == 0
        assert snapshot['total_duration_ms'] == 0.0
        assert snapshot['operation_counts'] == {}
        assert snapshot['recent_slow_queries'] == []
        assert snapshot['recent_errors'] == []
    
    def test_record_query(self):
        """Test recording query metrics."""
        metrics = DatabaseMetrics()
        
        metrics.record_query('save_roster_entry', 50.5, success=True)
        metrics.record_query('load_roster_entries', 25.3, success=True)
        metrics.record_query('search_similar', 15.2, success=False)
        
        assert metrics.query_count == 3
        assert metrics.error_count == 1
        assert metrics.total_duration_ms == pytest.approx(91.0, rel=0.1)
        assert metrics.operation_counts['save_roster_entry'] == 1
        assert metrics.operation_counts['load_roster_entries'] == 1
        assert metrics.operation_counts['search_similar'] == 1
    
    def test_record_slow_query(self):
        """Test recording slow queries."""
        metrics = DatabaseMetrics()
        
        metrics.record_slow_query(
            'search_similar',
            250.5,
            {'tenant_id': 'test-tenant', 'top_k': 10}
        )

        assert metrics.slow_query_count == 1
        slow_query = metrics.snapshot()['recent_slow_queries'][0]
        assert slow_query['operation'] == 'search_similar'
        assert slow_query['duration_ms'] == 250.5
        assert slow_query['tenant_id'] == 'test-tenant'
        assert slow_query['top_k'] == 10
        assert 'timestamp' in slow_query
    
    def test_slow_queries_max_100(self):
        """Test that slow queries list is limited to 100 entries."""
        metrics = DatabaseMetrics()
        
        # Add 150 slow queries
        for i in range(150):
            metrics.record_slow_query(f'operation_{i}', 100 + i, {'index': i})

        recent = metrics.snapshot()['recent_slow_queries']
        assert len(recent) == 100
        assert recent[0]['operation'] == 'operation_50'
        assert recent[-1]['operation'] == 'operation_149'
    
    def test_get_stats(self):
        """Test getting statistics summary."""
        metrics = DatabaseMetrics()
        
        metrics.record_query('save', 50.0, success=True)
        metrics.record_query('load', 30.0, success=True)
        metrics.record_query('search', 120.0, success=True)
        metrics.record_slow_query('search', 120.0, {'info': 'test'})
        
        stats = metrics.snapshot()

        assert stats['query_count'] == 3
        assert stats['slow_query_count'] == 1
        assert stats['error_count'] == 0
        assert stats['avg_duration_ms'] == pytest.approx(66.67, rel=0.1)
        assert stats['total_duration_ms'] == 200.0
        assert 'operation_counts' in stats
        assert 'recent_slow_queries' in stats
        assert len(stats['recent_slow_queries']) == 1


class TestPostgreSQLMetrics:
    """Test metrics integration in PostgreSQLStorageAdapter."""
    
    @pytest.fixture
    def mock_adapter(self, monkeypatch):
        """Create adapter with mocked database connection."""
        # Mock the database URL
        monkeypatch.setenv("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
        
        # Mock SQLAlchemy engine and session
        with patch('roster.adapters.postgresql_storage_adapter.create_engine_with_pool') as mock_engine, \
             patch('roster.adapters.postgresql_storage_adapter.verify_pgvector_extension'):
            mock_pool = MagicMock()
            mock_pool.size.return_value = 5
            mock_pool.checkedin.return_value = 3
            mock_pool.checkedout.return_value = 2
            mock_pool.overflow.return_value = 0
            mock_engine.return_value.dispose = MagicMock()
            mock_engine.return_value.pool = mock_pool

            adapter = PostgreSQLStorageAdapter(
                tenant_id="test-tenant",
                slow_query_threshold_ms=50.0
            )

            yield adapter
    
    def test_slow_query_threshold_initialization(self, mock_adapter):
        """Test that slow query threshold is set correctly."""
        assert mock_adapter.slow_query_threshold_ms == 50.0
    
    def test_get_metrics(self, mock_adapter):
        """Test retrieving metrics from adapter."""
        # Reset metrics first
        mock_adapter.reset_metrics()
        
        metrics = mock_adapter.get_metrics()

        assert 'query_count' in metrics
        assert 'slow_query_count' in metrics
        assert 'error_count' in metrics
        assert 'avg_duration_ms' in metrics
        assert 'connection_pool' in metrics
        
        pool_metrics = metrics['connection_pool']
        assert pool_metrics['size'] == 5
        assert pool_metrics['checked_in'] == 3
        assert pool_metrics['checked_out'] == 2
        assert 'utilisation_percent' in pool_metrics
    
    def test_reset_metrics(self, mock_adapter):
        """Test resetting metrics."""
        # Add some metrics
        mock_adapter._metrics.record_query('test', 100.0, success=True)
        assert mock_adapter._metrics.query_count > 0

        mock_adapter.reset_metrics()
        assert mock_adapter._metrics.query_count == 0


class TestTimedOperations:
    """Test the _timed_operation context manager."""
    
    @pytest.fixture
    def mock_adapter_with_session(self, monkeypatch):
        """Create adapter with mocked database for timing tests."""
        monkeypatch.setenv("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
        
        with patch('roster.adapters.postgresql_storage_adapter.create_engine_with_pool'), \
             patch('roster.adapters.postgresql_storage_adapter.verify_pgvector_extension'):
            adapter = PostgreSQLStorageAdapter(
                tenant_id="test-tenant",
                slow_query_threshold_ms=50.0
            )
            
            # Reset metrics
            adapter.reset_metrics()
            
            yield adapter
    
    def test_timed_operation_records_duration(self, mock_adapter_with_session):
        """Test that timed operations record duration."""
        adapter = mock_adapter_with_session
        
        with adapter._timed_operation('test_op', key='value'):
            time.sleep(0.01)  # 10ms
        
        metrics = adapter.get_metrics()
        assert metrics['query_count'] == 1
        # Allow for scheduling jitter on different platforms; we just need a non-trivial duration
        assert metrics['avg_duration_ms'] >= 5.0
        assert 'test_op' in metrics['operation_counts']
    
    def test_timed_operation_detects_slow_query(self, mock_adapter_with_session):
        """Test that slow queries are detected and logged."""
        adapter = mock_adapter_with_session
        
        adapter._slow_query_threshold_ms = 1.0

        with patch.object(adapter_module.logger, "warning") as mock_warning:
            with adapter._timed_operation('slow_op', detail='test'):
                time.sleep(0.02)  # 20ms, above 1ms threshold

        metrics = adapter.get_metrics()
        assert metrics['slow_query_count'] == 1
        assert mock_warning.called
        warning_args = mock_warning.call_args[0]
        assert "Slow query detected" in warning_args[0]
    
    def test_timed_operation_handles_errors(self, mock_adapter_with_session):
        """Test that errors are recorded in metrics."""
        adapter = mock_adapter_with_session
        
        with pytest.raises(ValueError):
            with adapter._timed_operation('error_op'):
                raise ValueError("Test error")
        
        metrics = adapter.get_metrics()
        assert metrics['error_count'] == 1


class TestStructuredLogging:
    """Test structured logging output."""
    
    @pytest.fixture
    def mock_adapter_logging(self, monkeypatch):
        """Create adapter with logging configured."""
        monkeypatch.setenv("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
        
        with patch('roster.adapters.postgresql_storage_adapter.create_engine_with_pool'), \
             patch('roster.adapters.postgresql_storage_adapter.verify_pgvector_extension'):
            adapter = PostgreSQLStorageAdapter(
                tenant_id="logging-test-tenant",
                slow_query_threshold_ms=100.0
            )
            yield adapter
    
    def test_operation_logging_includes_context(self, mock_adapter_logging):
        """Test that operations log with full context."""
        adapter = mock_adapter_logging
        
        with patch.object(adapter_module.logger, "debug") as mock_debug:
            with adapter._timed_operation('test_op', unique_id='test-123', model='test-model'):
                pass

        assert mock_debug.called
        debug_args_list = [args for args, _ in mock_debug.call_args_list]
        assert any('database operation' in args[0] for args in debug_args_list)
        assert any('operation=test_op' in args[0] or 'test_op' in ' '.join(map(str, args)) for args in debug_args_list)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
