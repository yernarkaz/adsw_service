from functools import wraps
from concurrent.futures import ThreadPoolExecutor

from tornado.platform.asyncio import to_tornado_future


def blocking(method):
    """Wraps the method in an async method, and executes the function on `self.executor`."""
    @wraps(method)
    async def wrapper(self, *args, **kwargs):
        future = self.executor.submit(method, self, *args, **kwargs)
        return await to_tornado_future(future)
    return wrapper


def check_data(datasource, datasource_id):
    pass
