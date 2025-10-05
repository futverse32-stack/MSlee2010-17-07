import logging

def setup_logger(name=__name__, level=logging.INFO):
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    )
    return logging.getLogger(name)
