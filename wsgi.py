# -*- coding: utf-8 -*-
"""
    wsgi
    ~~~~

    entrypoint wsgi script
"""

from werkzeug.serving import run_simple
from werkzeug.wsgi import DispatcherMiddleware

from recommender import app as recommender

application = DispatcherMiddleware(recommender.create_app(),mounts={
  #'/mount1': sample_application2.create_app(), #Could have multiple API-applications at different mount points
  })

if __name__ == "__main__":
    run_simple('0.0.0.0', 4000, application, use_reloader=False, use_debugger=True)
