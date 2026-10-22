#!/usr/bin/env python
import os
import sys
import logging

# Configure structured logging: [Job/Operation] - [Category/Level] - [Detail Message]
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] - [%(name)s] - [%(levelname)s] - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("Doctor")

def main() -> None:
    logger.info("Starting workspace diagnostic checks...")
    
    # 1. Bootstrap Django settings
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'RouteFinder.settings')
    try:
        import django
        django.setup()
        logger.info("Django bootstrap successful.")
    except Exception as e:
        logger.critical(f"Failed to bootstrap Django: {e}")
        sys.exit(1)
        
    from django.conf import settings
    
    # 2. Check Database Connection & Migrations
    from django.db import connections
    from django.db.utils import OperationalError
    
    db_conn = connections['default']
    db_settings = db_conn.settings_dict
    engine = db_settings.get('ENGINE', 'unknown')
    db_name = db_settings.get('NAME', 'unknown')
    db_host = db_settings.get('HOST') or 'local'
    logger.info(f"Checking database connection to {engine} (Database: '{db_name}', Host: '{db_host}')...")
    
    try:
        db_conn.cursor()
        logger.info(f"Database connection successful ({engine} - Database: '{db_name}').")
    except OperationalError as e:
        logger.error(f"Database connection failed: {e}")
        sys.exit(1)
        
    logger.info("Checking for unapplied database migrations...")
    from django.core.management import call_command
    import io
    
    try:
        out = io.StringIO()
        call_command('showmigrations', stdout=out)
        migrations_output = out.getvalue()
        unapplied = []
        for line in migrations_output.splitlines():
            if '[ ]' in line:
                unapplied.append(line.strip())
        
        if unapplied:
            logger.warning(f"Unapplied migrations detected:\n" + "\n".join(unapplied))
        else:
            logger.info("All database migrations are fully applied.")
    except Exception as e:
        logger.error(f"Failed to check migrations: {e}")
        
    # 3. Check environment configurations
    mock_mode = getattr(settings, 'MOCK_MODE', False)
    logger.info(f"MOCK_MODE configuration: {mock_mode}")
    
    google_maps_key = getattr(settings, 'GOOGLE_MAPS_API_KEY', '')
    if google_maps_key:
        logger.info("GOOGLE_MAPS_API_KEY is configured.")
    else:
        if mock_mode:
            logger.info("GOOGLE_MAPS_API_KEY is not configured (OK in MOCK_MODE).")
        else:
            logger.error("GOOGLE_MAPS_API_KEY is missing in non-mock mode! Route solving will fail.")
            
    # 4. Check AI service reachability (Ollama / OpenAI)
    ollama_url = getattr(settings, 'OLLAMA_BASE_URL', '')
    if ollama_url:
        logger.info(f"Ollama base URL: {ollama_url}")
        if not mock_mode:
            import requests
            try:
                # Test Ollama API endpoint tag list/version
                res = requests.get(f"{ollama_url.rstrip('/')}/api/tags", timeout=5)
                if res.status_code == 200:
                    logger.info("Local Ollama service is reachable.")
                else:
                    logger.warning(f"Ollama service returned status code {res.status_code}.")
            except Exception as e:
                logger.warning(f"Local Ollama service is unreachable: {e}")
    else:
        logger.info("Ollama is not configured.")

    logger.info("Workspace diagnostic checks completed.")

if __name__ == '__main__':
    main()
