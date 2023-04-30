def configure_logging(pretty=True):
    import logging
    import structlog

    logging.basicConfig(
        level=logging.INFO
    )

    processors = (
        [
            structlog.dev.ConsoleRenderer(colors=True),
        ]
        if pretty
        else []
    )
    structlog.configure(
        processors=processors,
        cache_logger_on_first_use=True,
    )
