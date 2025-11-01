#!/usr/bin/env python3
"""
Logging Configuration for PyFFMPEG
Provides structured logging with performance metrics and user-friendly error messages
"""

import logging
import logging.handlers
import os
import sys
import time
from typing import Dict, Any, Optional
from pathlib import Path
from PySide6.QtCore import QObject, Signal

from config import LogConfig, AppConfig


class PerformanceMetrics:
    """Track performance metrics for conversion operations"""

    def __init__(self):
        self.conversion_times: Dict[str, float] = {}
        self.conversion_speeds: Dict[str, float] = {}  # MB/s
        self.error_counts: Dict[str, int] = {}
        self.hardware_usage: Dict[str, Any] = {}

    def start_conversion(self, file_path: str) -> None:
        """Start tracking conversion for a file"""
        self.conversion_times[file_path] = time.time()

    def finish_conversion(self, file_path: str, file_size_mb: float) -> None:
        """Finish tracking conversion and calculate speed"""
        if file_path in self.conversion_times:
            elapsed = time.time() - self.conversion_times[file_path]
            self.conversion_speeds[file_path] = (
                file_size_mb / elapsed if elapsed > 0 else 0
            )
            del self.conversion_times[file_path]

    def record_error(self, error_type: str) -> None:
        """Record an error occurrence"""
        self.error_counts[error_type] = self.error_counts.get(error_type, 0) + 1

    def get_average_speed(self) -> float:
        """Get average conversion speed in MB/s"""
        speeds = list(self.conversion_speeds.values())
        return sum(speeds) / len(speeds) if speeds else 0.0

    def get_error_rate(self) -> float:
        """Get overall error rate as percentage"""
        total_conversions = len(self.conversion_speeds) + sum(
            self.error_counts.values()
        )
        total_errors = sum(self.error_counts.values())
        return (
            (total_errors / total_conversions * 100) if total_conversions > 0 else 0.0
        )


class UserFriendlyFormatter(logging.Formatter):
    """Custom formatter for user-friendly log messages"""

    # Color codes for different log levels
    COLORS = {
        "DEBUG": "\033[36m",  # Cyan
        "INFO": "\033[32m",  # Green
        "WARNING": "\033[33m",  # Yellow
        "ERROR": "\033[31m",  # Red
        "CRITICAL": "\033[35m",  # Magenta
        "RESET": "\033[0m",  # Reset
    }

    # User-friendly prefixes
    PREFIXES = {
        "DEBUG": "🔍",
        "INFO": "ℹ️",
        "WARNING": "⚠️",
        "ERROR": "❌",
        "CRITICAL": "🚨",
    }

    def format(self, record):
        # Add color and emoji prefix
        if hasattr(record, "no_color") and record.no_color:
            record.levelname = f"[{record.levelname}]"
        else:
            color = self.COLORS.get(record.levelname, "")
            reset = self.COLORS["RESET"]
            prefix = self.PREFIXES.get(record.levelname, "📝")
            record.levelname = f"{color}{prefix} {record.levelname}{reset}"

        # Format the message
        formatted = super().format(record)

        # Add actionable suggestions for errors
        if record.levelno >= logging.ERROR and hasattr(record, "suggestion"):
            formatted += f"\n💡 Suggestion: {record.suggestion}"

        return formatted


class PyFFMPEGLogger(QObject):
    """Main logger class for PyFFMPEG with Qt signal integration"""

    # Signals for UI integration
    log_message = Signal(str, str)  # message, level
    error_occurred = Signal(str, str)  # error_message, suggestion
    performance_update = Signal(dict)  # performance metrics

    def __init__(self, name: str = "PyFFMPEG"):
        super().__init__()
        self.name = name
        self.logger = logging.getLogger(name)
        self.metrics = PerformanceMetrics()
        self._setup_logging()

    def _setup_logging(self) -> None:
        """Set up logging configuration"""
        self.logger.setLevel(logging.DEBUG)

        # Clear any existing handlers
        self.logger.handlers.clear()

        # Create formatters
        detailed_formatter = logging.Formatter(
            "%(asctime)s | %(name)s | %(levelname)s | %(filename)s:%(lineno)d | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        user_formatter = UserFriendlyFormatter(
            "%(asctime)s | %(levelname)s | %(message)s", datefmt="%H:%M:%S"
        )

        # Console handler for user-friendly output
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(user_formatter)
        self.logger.addHandler(console_handler)

        # File handler for detailed logging
        log_dir = Path(os.getcwd()) / "logs"
        log_dir.mkdir(exist_ok=True)

        file_handler = logging.handlers.RotatingFileHandler(
            log_dir / f"{self.name.lower()}.log",
            maxBytes=LogConfig.MAIN_LOG_MAX_SIZE * 1024,  # Convert to bytes
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(detailed_formatter)
        self.logger.addHandler(file_handler)

        # Performance log handler
        perf_handler = logging.handlers.RotatingFileHandler(
            log_dir / f"{self.name.lower()}_performance.log",
            maxBytes=LogConfig.PROCESS_LOG_MAX_SIZE * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        perf_handler.setLevel(logging.INFO)
        perf_handler.setFormatter(detailed_formatter)
        perf_handler.addFilter(lambda record: hasattr(record, "performance"))
        self.logger.addHandler(perf_handler)

    def debug(self, message: str, **kwargs) -> None:
        """Log debug message"""
        self.logger.debug(message, extra=kwargs)
        self.log_message.emit(message, "DEBUG")

    def info(self, message: str, **kwargs) -> None:
        """Log info message"""
        self.logger.info(message, extra=kwargs)
        self.log_message.emit(message, "INFO")

    def warning(self, message: str, suggestion: str = None, **kwargs) -> None:
        """Log warning message with optional suggestion"""
        extra = kwargs.copy()
        if suggestion:
            extra["suggestion"] = suggestion
        self.logger.warning(message, extra=extra)
        self.log_message.emit(message, "WARNING")

    def error(self, message: str, suggestion: str = None, **kwargs) -> None:
        """Log error message with optional suggestion"""
        extra = kwargs.copy()
        if suggestion:
            extra["suggestion"] = suggestion
        self.logger.error(message, extra=extra)
        self.log_message.emit(message, "ERROR")
        self.error_occurred.emit(
            message, suggestion or "Check the log file for details"
        )
        self.metrics.record_error("general")

    def critical(self, message: str, suggestion: str = None, **kwargs) -> None:
        """Log critical message with optional suggestion"""
        extra = kwargs.copy()
        if suggestion:
            extra["suggestion"] = suggestion
        self.logger.critical(message, extra=extra)
        self.log_message.emit(message, "CRITICAL")
        self.error_occurred.emit(
            message,
            suggestion
            or "This is a critical error - please check system configuration",
        )
        self.metrics.record_error("critical")

    def log_performance(
        self, operation: str, duration: float, details: Dict[str, Any] = None
    ) -> None:
        """Log performance metrics"""
        details = details or {}
        message = f"Performance: {operation} took {duration:.2f}s"

        extra = {
            "performance": True,
            "operation": operation,
            "duration": duration,
            **details,
        }

        self.logger.info(message, extra=extra)

        # Emit performance update signal
        perf_data = {
            "operation": operation,
            "duration": duration,
            "timestamp": time.time(),
            **details,
        }
        self.performance_update.emit(perf_data)

    def log_ffmpeg_start(self, file_path: str, args: list) -> None:
        """Log FFmpeg process start"""
        self.info(f"🚀 Starting FFmpeg conversion: {os.path.basename(file_path)}")
        self.debug(f"FFmpeg args: {' '.join(args)}")
        self.metrics.start_conversion(file_path)

    def log_ffmpeg_error(
        self, file_path: str, error_code: int, error_message: str
    ) -> None:
        """Log FFmpeg process error with suggestions"""
        suggestions = {
            1: "Check if the input file is valid and accessible",
            2: "Verify FFmpeg is properly installed and in PATH",
            126: "Check file permissions for input and output directories",
            127: "FFmpeg command not found - check installation",
        }

        suggestion = suggestions.get(
            error_code, "Check FFmpeg documentation for this error code"
        )

        self.error(
            f"FFmpeg conversion failed for {os.path.basename(file_path)}: {error_message} (exit code: {error_code})",
            suggestion=suggestion,
        )
        self.metrics.record_error("ffmpeg_process")

    def log_ffmpeg_success(self, file_path: str, file_size_mb: float) -> None:
        """Log successful FFmpeg conversion"""
        self.info(f"✅ Conversion completed: {os.path.basename(file_path)}")
        self.metrics.finish_conversion(file_path, file_size_mb)

    def log_hardware_detection(self, gpu_info: str, encoders: list) -> None:
        """Log hardware detection results"""
        if gpu_info:
            self.info(
                f"🎮 GPU detected: {gpu_info.split('GPU 0:')[1].split('(')[0].strip() if 'GPU 0:' in gpu_info else 'Unknown GPU'}"
            )
        else:
            self.warning(
                "No NVIDIA GPU detected",
                suggestion="Consider using CPU encoding or install NVIDIA drivers",
            )

        self.debug(
            f"Available encoders: {', '.join(encoders) if encoders else 'None detected'}"
        )

    def log_process_timeout(self, process_name: str, timeout_seconds: int) -> None:
        """Log process timeout"""
        self.error(
            f"Process {process_name} timed out after {timeout_seconds} seconds",
            suggestion="Check system resources or increase timeout in configuration",
        )
        self.metrics.record_error("timeout")

    def get_metrics_summary(self) -> Dict[str, Any]:
        """Get current performance metrics summary"""
        return {
            "average_speed_mbps": self.metrics.get_average_speed(),
            "error_rate_percent": self.metrics.get_error_rate(),
            "total_conversions": len(self.metrics.conversion_speeds),
            "total_errors": sum(self.metrics.error_counts.values()),
            "error_breakdown": self.metrics.error_counts.copy(),
        }


# Global logger instance
_logger_instance: Optional[PyFFMPEGLogger] = None


def get_logger(name: str = "PyFFMPEG") -> PyFFMPEGLogger:
    """Get or create the global logger instance"""
    global _logger_instance
    if _logger_instance is None:
        _logger_instance = PyFFMPEGLogger(name)
    return _logger_instance


def setup_logging(debug_mode: bool = False) -> PyFFMPEGLogger:
    """Set up logging for the application"""
    logger = get_logger()

    if debug_mode:
        # Enable debug logging to console in debug mode
        for handler in logger.logger.handlers:
            if isinstance(handler, logging.StreamHandler):
                handler.setLevel(logging.DEBUG)

    logger.info(f"🔧 {AppConfig.APP_NAME} v{AppConfig.APP_VERSION} logging initialized")
    return logger


# Convenience functions for common logging operations
def log_startup() -> None:
    """Log application startup"""
    logger = get_logger()
    logger.info(f"🚀 Starting {AppConfig.APP_NAME} v{AppConfig.APP_VERSION}")
    logger.debug(f"Python version: {sys.version}")
    logger.debug(f"Working directory: {os.getcwd()}")


def log_shutdown() -> None:
    """Log application shutdown with metrics summary"""
    logger = get_logger()
    metrics = logger.get_metrics_summary()

    logger.info(f"🛑 Shutting down {AppConfig.APP_NAME}")
    logger.log_performance(
        "session_summary",
        0,  # No duration for summary
        metrics,
    )

    if metrics["total_conversions"] > 0:
        logger.info(
            f"📊 Session summary: {metrics['total_conversions']} conversions, "
            f"{metrics['average_speed_mbps']:.1f} MB/s average speed, "
            f"{metrics['error_rate_percent']:.1f}% error rate"
        )
