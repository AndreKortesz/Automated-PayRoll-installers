"""
Application Configuration
Mos-GSM Salary Service
"""

import os
import logging

# ============================================================================
# DEBUG MODE
# ============================================================================
# Set DEBUG_MODE=true in environment for verbose logging
# In production, leave it unset or set to false

DEBUG_MODE = os.getenv("DEBUG_MODE", "false").lower() in ("true", "1", "yes")

# ============================================================================
# LOGGING CONFIGURATION
# ============================================================================

def setup_logging():
    """Configure application logging"""
    log_level = logging.DEBUG if DEBUG_MODE else logging.INFO
    
    # Create formatter
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    
    # Remove existing handlers to avoid duplicates
    root_logger.handlers = []
    
    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)
    
    # Create app logger
    app_logger = logging.getLogger('mosgsm')
    app_logger.setLevel(log_level)
    
    return app_logger

# Initialize logger
logger = setup_logging()

# Log startup mode
if DEBUG_MODE:
    logger.debug("🔧 Debug mode enabled - verbose logging active")
else:
    logger.info("🚀 Production mode - minimal logging")

# ============================================================================
# DEFAULT CONFIGURATION
# ============================================================================
# SECURITY: API keys must be in environment variables, not in code

DEFAULT_CONFIG = {
    "base_address": "Москва, Сходненский тупик 16с4",
    "fuel_coefficient": 7,
    "fuel_max": 3000,
    "fuel_warning": 2000,
    "transport_amount": 1000,
    "transport_min_revenue": 10000,
    "transport_percent_min": 20,
    "transport_percent_max": 40,
    "diagnostic_percent": 50,
    "alarm_high_payment": 20000,
    "alarm_high_specialist": 3500,
    "standard_percents": [30, 50, 100],
    "yandex_api_key": os.getenv("YANDEX_GEOCODER_API_KEY", "")
}

# Warn if Yandex API key is not configured
if not DEFAULT_CONFIG["yandex_api_key"]:
    logger.warning("⚠️ YANDEX_GEOCODER_API_KEY not set in environment. Geocoding will not work.")


# ============================================================================
# SESSION STORAGE
# ============================================================================
# ⚠️  WARNING: This is in-memory storage. Sessions will be lost on server restart.
# For production with multiple instances, consider using:
#   - Redis (recommended)
#   - Database-backed sessions
#   - JWT tokens
# On Railway with single instance, this is acceptable but sessions reset on deploy.

session_data = {}

# Distance cache to avoid repeated API calls
# Note: Also in-memory, resets on restart. Consider Redis for persistence.
distance_cache = {}
