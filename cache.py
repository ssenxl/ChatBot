import redis
import json
import os
from datetime import timedelta
from functools import wraps

# Redis connection for caching
REDIS_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379')
try:
    redis_client = redis.from_url(REDIS_URL)
    redis_client.ping()  # Test connection
    REDIS_AVAILABLE = True
except:
    REDIS_AVAILABLE = False
    redis_client = None

# In-memory cache fallback
memory_cache = {}

def cache_result(expiration=300):
    """Decorator to cache function results"""
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            # Create cache key
            cache_key = f"{f.__name__}:{str(args)}:{str(kwargs)}"
            
            # Try to get from cache
            if REDIS_AVAILABLE:
                try:
                    cached_result = redis_client.get(cache_key)
                    if cached_result:
                        return json.loads(cached_result)
                except:
                    pass
            else:
                # Fallback to memory cache
                if cache_key in memory_cache:
                    cached_data, cached_time = memory_cache[cache_key]
                    if (datetime.datetime.now() - cached_time).seconds < expiration:
                        return cached_data
            
            # Execute function
            result = f(*args, **kwargs)
            
            # Store in cache
            try:
                if REDIS_AVAILABLE:
                    redis_client.setex(
                        cache_key, 
                        expiration, 
                        json.dumps(result, default=str)
                    )
                else:
                    memory_cache[cache_key] = (result, datetime.datetime.now())
            except:
                pass
            
            return result
        return decorated
    return decorator

def clear_cache(pattern=None):
    """Clear cache"""
    if REDIS_AVAILABLE:
        try:
            if pattern:
                keys = redis_client.keys(pattern)
                if keys:
                    redis_client.delete(*keys)
            else:
                redis_client.flushdb()
        except:
            pass
    else:
        if pattern:
            keys_to_remove = [k for k in memory_cache.keys() if pattern in k]
            for key in keys_to_remove:
                del memory_cache[key]
        else:
            memory_cache.clear()

def get_cache_stats():
    """Get cache statistics"""
    if REDIS_AVAILABLE:
        try:
            info = redis_client.info()
            return {
                'type': 'redis',
                'used_memory': info.get('used_memory_human', 'N/A'),
                'connected_clients': info.get('connected_clients', 'N/A'),
                'keyspace_hits': info.get('keyspace_hits', 0),
                'keyspace_misses': info.get('keyspace_misses', 0)
            }
        except:
            pass
    
    return {
        'type': 'memory',
        'cache_size': len(memory_cache),
        'max_size': 1000  # Simple limit for memory cache
    }
