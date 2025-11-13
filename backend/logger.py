import os
import sys
import logging
from logging.handlers import RotatingFileHandler
from threading import Lock

class StreamToLogger:
    """
    Redirects stdout/stderr (like print statements) into the logger.
    """
    def __init__(self, logger, log_level=logging.INFO):
        self.logger = logger
        self.log_level = log_level
        self.linebuf = ''

    def isatty(self):
        return False

    def write(self, buf):
        self.linebuf += buf
        if '\n' in self.linebuf:
            lines = self.linebuf.split('\n')
            for line in lines[:-1]:
                message = line.strip()
                if message:
                    self.logger.log(self.log_level, message)
            self.linebuf = lines[-1]

    def flush(self):
        message = self.linebuf.strip()
        if message:
            self.logger.log(self.log_level, message)
        self.linebuf = ''


_log_lock = Lock()
_root_logger_configured = False


def get_logger(name):
    """
    Creates and returns a thread-safe logger that logs to both console and file.
    """
    global _root_logger_configured
    
    logger = logging.getLogger(name)

    # Configure root logger only once
    if not _root_logger_configured:
        # Get the backend directory (where this logger.py file is located)
        backend_dir = os.path.dirname(os.path.abspath(__file__))
        
        # Create logs directory path
        log_dir = os.path.join(backend_dir, "logs")
        
        # Ensure the directory exists with proper permissions
        try:
            os.makedirs(log_dir, exist_ok=True)
            print(f"✅ Log directory ensured at: {log_dir}")
        except Exception as e:
            print(f"❌ Failed to create log directory: {e}")
            # Fall back to current directory if backend/logs fails
            log_dir = "."
            print(f"⚠️ Using fallback log directory: {log_dir}")

        # Full path to log file
        log_file = os.path.join(log_dir, "app.log")
        print(f"📝 Log file will be created at: {log_file}")

        # Configure root logger
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.DEBUG)
        
        # Remove any existing handlers
        root_logger.handlers.clear()

        # File handler with rotation
        try:
            file_handler = RotatingFileHandler(
                log_file,
                maxBytes=10 * 1024 * 1024,  # 10MB
                backupCount=5,
                encoding="utf-8"
            )
            file_handler.setLevel(logging.DEBUG)
            
            # Console handler for live logs
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setLevel(logging.DEBUG)
            
            # Detailed formatter
            formatter = logging.Formatter(
                "%(asctime)s - %(levelname)s - %(name)s - %(funcName)s:%(lineno)d - %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S"
            )
            
            file_handler.setFormatter(formatter)
            console_handler.setFormatter(formatter)

            # Add both handlers to root logger
            root_logger.addHandler(file_handler)
            root_logger.addHandler(console_handler)
            
            print(f"✅ Root logger initialized successfully")
            _root_logger_configured = True
            
        except Exception as e:
            print(f"❌ Failed to create log handlers: {e}")
            # At minimum, add console handler
            console_handler = logging.StreamHandler(sys.stdout)
            formatter = logging.Formatter(
                "%(asctime)s - %(levelname)s - %(name)s - %(message)s"
            )
            console_handler.setFormatter(formatter)
            root_logger.addHandler(console_handler)
            root_logger.setLevel(logging.DEBUG)
            _root_logger_configured = True

    return logger


def redirect_prints_to_logging(logger):
    """
    Redirects print() and uncaught exceptions to the provided logger.
    """
    stdout_logger = StreamToLogger(logger, log_level=logging.INFO)
    sys.stdout = stdout_logger

    stderr_logger = StreamToLogger(logger, log_level=logging.ERROR)
    sys.stderr = stderr_logger