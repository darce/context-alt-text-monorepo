import logging
import sys

def setup_logging():
    # Define a more detailed format
    log_format = '%(asctime)s - %(name)s - %(levelname)s - %(module)s:%(funcName)s:%(lineno)d - %(message)s'
    
    # Get the root logger
    root_logger = logging.getLogger()
    
    # Set the level for the root logger. 
    # This will be the default level for all loggers unless overridden.
    # Uvicorn's --log-level will also influence this, especially for its own logs.
    root_logger.setLevel(logging.DEBUG) 
    
    # Remove any existing handlers from the root logger to avoid duplicate logs
    if root_logger.hasHandlers():
        root_logger.handlers.clear()
        
    # Create a handler for stdout
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setLevel(logging.DEBUG) # Process all messages from DEBUG upwards
    
    # Create a formatter and set it for the handler
    formatter = logging.Formatter(log_format)
    stdout_handler.setFormatter(formatter)
    
    # Add the handler to the root logger
    root_logger.addHandler(stdout_handler)
    
    # You can also configure specific loggers here if needed
    # For example, to make a specific library less verbose:
    # logging.getLogger("some_library").setLevel(logging.WARNING)
    
    # Reduce noise from HuggingFace Hub file locking system
    logging.getLogger("filelock").setLevel(logging.INFO)  # Suppress DEBUG file lock messages
    logging.getLogger("huggingface_hub").setLevel(logging.INFO)  # Reduce HF Hub verbosity

    logging.info("Logging configured via config.logging_config.setup_logging()")
    logging.debug("DEBUG level test message from setup_logging.")

if __name__ == '__main__':
    # This part is for testing the logging configuration directly
    setup_logging()
    
    # Test messages from different loggers
    logger_test_app = logging.getLogger("test_app")
    logger_test_module = logging.getLogger("test_app.module")

    logger_test_app.debug("This is a debug message from test_app.")
    logger_test_app.info("This is an info message from test_app.")
    logger_test_app.warning("This is a warning message from test_app.")
    
    logger_test_module.debug("This is a debug message from test_app.module.")
    logger_test_module.info("This is an info message from test_app.module.")
    
    # Test uvicorn specific loggers (simulated)
    # In a real app, uvicorn would create these.
    # logger_uvicorn_access = logging.getLogger("uvicorn.access")
    # logger_uvicorn_error = logging.getLogger("uvicorn.error")
    # logger_uvicorn_access.info("Simulated uvicorn access log.") # Typically INFO
    # logger_uvicorn_error.error("Simulated uvicorn error log.")
