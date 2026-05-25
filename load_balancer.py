import threading
import queue
import time
from concurrent.futures import ThreadPoolExecutor
from functools import wraps

class LoadBalancer:
    def __init__(self, max_workers=10):
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self.request_queue = queue.Queue()
        self.active_requests = 0
        self.max_concurrent = max_workers
        
    def submit_task(self, func, *args, **kwargs):
        """Submit task to thread pool"""
        if self.active_requests >= self.max_concurrent:
            return None, "Server busy - too many concurrent requests"
        
        self.active_requests += 1
        try:
            future = self.executor.submit(func, *args, **kwargs)
            return future, None
        except Exception as e:
            self.active_requests -= 1
            return None, str(e)
    
    def get_status(self):
        """Get load balancer status"""
        return {
            'active_requests': self.active_requests,
            'max_concurrent': self.max_concurrent,
            'queue_size': self.request_queue.qsize()
        }

# Global load balancer instance
load_balancer = LoadBalancer()

def async_route(max_workers=5):
    """Decorator for async route handling"""
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            future, error = load_balancer.submit_task(f, *args, **kwargs)
            
            if error:
                return {'success': False, 'message': error}, 503
            
            try:
                result = future.result(timeout=30)  # 30 second timeout
                return result
            except TimeoutError:
                return {'success': False, 'message': 'Request timeout'}, 504
            except Exception as e:
                return {'success': False, 'message': str(e)}, 500
            finally:
                load_balancer.active_requests -= 1
        
        return decorated
    return decorator

def health_check():
    """Health check endpoint"""
    status = load_balancer.get_status()
    
    # Determine health status
    if status['active_requests'] >= status['max_concurrent'] * 0.9:
        health = 'critical'
    elif status['active_requests'] >= status['max_concurrent'] * 0.7:
        health = 'warning'
    else:
        health = 'healthy'
    
    return {
        'status': health,
        'load_balancer': status,
        'timestamp': time.time()
    }
