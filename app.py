import tornado.httpserver
import tornado.ioloop
import tornado.web
from tornado.options import options
from settings import settings, mongo_settings
from urls import url_patterns
from utils.db import connect_mongo
import pylibmc


class ADSWApp(tornado.web.Application):
    def __init__(self, *args, **kwargs):
        db = connect_mongo(mongo_settings, **kwargs)
        self.mc = pylibmc.Client(["127.0.0.1"], binary=True,
                                 behaviors={"tcp_nodelay": True, "ketama": True})
        super(ADSWApp, self).__init__(url_patterns, db=db,
                                      *args, **dict(settings, **kwargs))


def main():
    app = ADSWApp()
    http_server = tornado.httpserver.HTTPServer(app)
    http_server.listen(options.port)
    tornado.ioloop.IOLoop.instance().start()

if __name__ == '__main__':
    main()
