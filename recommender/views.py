from flask import current_app, Blueprint, request
from flask.ext.restful import Resource
import time
import inspect
import sys

from utils.recommender import get_recommendations

blueprint = Blueprint(
      'recommender',
      __name__,
      static_folder=None,
)

class Recommender(Resource):
    """"Return recommender results for a given bibcode"""
    scopes = []
    rate_limit = [1000,60*60*24]
    def get(self, bibcode):
       try:
           results = get_recommendations(bibcode)
       except Exception, err:
           return {'msg': 'Unable to get results! (%s)' % err}, 500
       return results

class Resources(Resource):
  '''Overview of available resources'''
  scopes = []
  rate_limit = [1000,60*60*24]
  def get(self):
    func_list = {}

    clsmembers = [i[1] for i in inspect.getmembers(sys.modules[__name__], inspect.isclass)]
    for rule in current_app.url_map.iter_rules():
      f = current_app.view_functions[rule.endpoint]
      #If we load this webservice as a module, we can't guarantee that current_app only has these views
      if not hasattr(f,'view_class') or f.view_class not in clsmembers:
        continue
      methods = f.view_class.methods
      scopes = f.view_class.scopes
      rate_limit = f.view_class.rate_limit
      description = f.view_class.__doc__
      func_list[rule.rule] = {'methods':methods,'scopes': scopes,'description': description,'rate_limit':rate_limit}
    return func_list, 200
