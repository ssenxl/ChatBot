workers = 2
threads = 4
worker_class = "gthread"
timeout = 120
keepalive = 5
preload_app = True
bind = "0.0.0.0:5000"


def post_fork(server, worker):
    from data_cache import get_data_cache
    get_data_cache().start()
