import sys
import time
import logging
from django.apps import AppConfig
from django.db.utils import OperationalError

logger = logging.getLogger(__name__)

class RoutefinderwebConfig(AppConfig):
    name = 'RouteFinderWeb'

    def ready(self) -> None:
        # Avoid running diagnostics during migrations, testing, and static compilation
        non_diagnostic_cmds = ['test', 'makemigrations', 'migrate', 'collectstatic', 'init_superuser']
        if any(cmd in sys.argv for cmd in non_diagnostic_cmds):
            return
            
        self.run_startup_diagnostics()

    def run_startup_diagnostics(self) -> None:
        from django.conf import settings
        
        # 1. Environment Config Validation
        mock_mode = getattr(settings, 'MOCK_MODE', False)
        
        secret_key = getattr(settings, 'SECRET_KEY', '')
        if not secret_key or secret_key == 'dev_secret_key_change_me_in_prod':
            logger.warning("[Startup] - [Configuration] - SECRET_KEY is set to default/dev value. Change this in production!")
            
        maps_key = getattr(settings, 'GOOGLE_MAPS_API_KEY', '')
        if not mock_mode and not maps_key:
            logger.error("[Startup] - [Configuration] - GOOGLE_MAPS_API_KEY is missing in non-mock mode! Server cannot function.")
            sys.exit(1)
            
        # 2. Pre-flight connection checks (Database reachability with exponential backoff)
        from django.db import connections
        
        db_conn = connections['default']
        db_settings = db_conn.settings_dict
        engine = db_settings.get('ENGINE', 'unknown')
        db_name = db_settings.get('NAME', 'unknown')
        db_host = db_settings.get('HOST') or 'local'
        db_user = db_settings.get('USER') or 'unknown'
        has_pw = bool(db_settings.get('PASSWORD'))
        logger.info(f"[Startup] - [Database] - Initializing database connection using {engine} (Database: '{db_name}', Host: '{db_host}', User: '{db_user}', Password set: {has_pw}).")
        
        max_retries = 3
        retry_delay = 2.0
        
        for attempt in range(1, max_retries + 1):
            try:
                db_conn.cursor()
                logger.info(f"[Startup] - [Database] - Database connection verified successfully ({engine} - Database: '{db_name}').")
                break
            except OperationalError as e:
                logger.warning(f"[Startup] - [Database] - Database connection to {engine} ('{db_name}' at {db_host}) failed (attempt {attempt}/{max_retries}). Retrying in {retry_delay}s... Error: {e}")
                if attempt == max_retries:
                    logger.error("[Startup] - [Database] - Database connection failed permanently. Terminating startup.")
                    sys.exit(1)
                time.sleep(retry_delay)
                retry_delay *= 2
