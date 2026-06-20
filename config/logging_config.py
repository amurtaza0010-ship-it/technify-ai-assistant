import logging
import sys

def setup_central_logger(name: str):
    """TAIA Centralised Logger Setup."""
    logger = logging.getLogger(name)
    
    # Check to avoid duplicate logs
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        handler = logging.StreamHandler(sys.stdout)
        
        # Professional format matching TAIA ERP standards
        formatter = logging.Formatter(
            '%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        
    return logger