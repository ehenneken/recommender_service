'''
Created on Nov 3, 2014

@author: ehenneken
'''
import os
import re
import sys
import time
from datetime import datetime
import simplejson as json
from itertools import groupby
from collections import defaultdict
import urllib
import numpy as np 
import operator
from .definitions import ASTkeywords
from sqlalchemy import Column, Integer, String, DateTime, Boolean, Float
from sqlalchemy.ext.declarative import DeclarativeMeta
from sqlalchemy.dialects import postgresql
from flask import current_app
from flask.ext.sqlalchemy import SQLAlchemy
from database import db, SQLAlchemy, CoReads, Clusters, Clustering, AlchemyEncoder

_basedir = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))

class SolrQueryError(Exception):
    pass

# Helper functions
# Data conversion
def flatten(items):
    """flatten(sequence) -> list

    Returns a single, flat list which contains all elements retrieved
    from the sequence and all recursively contained sub-sequences
    (iterables).

    Examples:
    >>> [1, 2, [3,4], (5,6)]
    [1, 2, [3, 4], (5, 6)]
    >>> flatten([[[1,2,3], (42,None)], [4,5], [6], 7, MyVector(8, 9, 10)])
    [1, 2, 3, 42, None, 4, 5, 6, 7, 8, 9, 10]"""

    result = []
    for item in items:
        if hasattr(item, '__iter__'):
            result.extend(flatten(item))
        else:
            result.append(item)
    return result

def merge_tuples(list1,list2):
    merged = defaultdict(int)
    merged.update(list1)
    for key, value in list2:
        merged[key] += value
    return merged.items()

def get_frequencies(l):
    '''
    For a list of items, return a list of tuples, consisting of
    unique items, augemented with their frequency in the original list
    '''
    tmp = [(k,len(list(g))) for k, g in groupby(sorted(l))]
    return sorted(tmp, key=operator.itemgetter(1),reverse=True)[:100]

def make_date(datestring):
    '''
    Turn an ADS publication data into an actual date
    '''
    pubdate = map(lambda a: int(a), datestring.split('-'))
    if pubdate[1] == 0:
        pubdate[1] = 1
    return datetime(pubdate[0],pubdate[1],1)

# Data retrieval
def get_normalized_keywords(bibc):
    '''
    For a given publication, construct a list of normalized keywords of this
    publication and its references
    '''
    keywords = []
    q = 'bibcode:%s or references(bibcode:%s)' % (bibc,bibc)
    try:
        # Get the information from Solr
        params = {'wt':'json', 'q':q, 'fl':'keyword_norm', 'rows': current_app.config['MAX_HITS']}
        query_url = current_app.config['SOLRQUERY_URL'] + "/?" + urllib.urlencode(params)
        resp = current_app.client.session.get(query_url).json()
    except SolrQueryError, e:
        app.logger.error("Solr keywords query for %s blew up (%s)" % (bibc,e))
        raise
    for doc in resp['response']['docs']:
        try:
            keywords += map(lambda a: a.lower(), doc['keyword_norm'])
        except:
            pass
    return filter(lambda a: a in ASTkeywords, keywords)

def get_article_data(biblist, check_references=True):
    '''
    Get basic article metadata for a list of bibcodes
    '''
    list = " OR ".join(map(lambda a: "bibcode:%s"%a, biblist))
    q = '%s' % list
    fl= 'bibcode,title,first_author,keyword_norm,reference,citation_count,pubdate'
    try:
        # Get the information from Solr
        params = {'wt':'json', 'q':q, 'fl':fl, 'sort':'pubdate desc, bibcode desc', 'rows': current_app.config['MAX_HITS']}
        query_url = current_app.config['SOLRQUERY_URL'] + "/?" + urllib.urlencode(params)
        resp = current_app.client.session.get(query_url).json()
    except SolrQueryError, e:
        app.logger.error("Solr article data query for %s blew up (%s)" % (str(biblist),e))
        raise
    results = resp['response']['docs']
    if check_references:
        results = filter(lambda a: 'reference' in a, results)
        return results
    else:
        data_dict = {}
        for doc in results:
            title = 'NA'
            if 'title' in doc: title = doc['title'][0]
            author = 'NA'
            if 'first_author' in doc: author = "%s,+"%doc['first_author'].split(',')[0]
            data_dict[doc['bibcode']] = {'title':title, 'author':author}
        return data_dict

def get_citing_papers(**args):
    citations = []
    bibcodes = args.get('bibcodes',[])
    list = " OR ".join(map(lambda a: "bibcode:%s"%a, bibcodes))
    q = '%s' % list
    fl= 'citation'
    try:
        # Get the information from Solr
        params = {'wt':'json', 'q':q, 'fl':fl, 'sort':'pubdate desc, bibcode desc', 'rows': current_app.config['MAX_HITS']}
        query_url = current_app.config['SOLRQUERY_URL'] + "/?" + urllib.urlencode(params)
        resp = current_app.client.session.get(query_url).json()
    except SolrQueryError, e:
        app.logger.error("Solr article data query for %s blew up (%s)" % (str(biblist),e))
        raise
    for doc in resp['response']['docs']:
        if 'citation' in doc:
            citations += doc['citation']
    return citations
#   
# Helper Functions: Data Processing
def make_paper_vector(bibc):
    '''
    Given a bibcode, retrieve the list of normalized keywords for this publication AND
    its references. Then contruct a vector of normalized frequencies. This is an ordered
    vector, i.e. the first entry is for the first normalized keyword etc etc etc
    '''
    data = get_normalized_keywords(bibc)
    if len(data) == 0:
        return []
    freq = dict((ASTkeywords.index(x), float(data.count(x))/float(len(data))) for x in data)
    FreqVec = [0.0]*len(ASTkeywords)
    for i in freq.keys():
        FreqVec[i] = freq[i]
    return FreqVec

def project_paper(pvector,pcluster=None):
    '''
    If no cluster is specified, this routine projects a paper vector (with normalized frequencies
    for ALL normalized keywords) onto the reduced 100-dimensional space. When a cluster is specified
    the this is a cluster-specific projection to further reduce the dimensionality to 5 dimensions
    '''
    if not pcluster:
        pcluster = -1
    matrix_file = "%s/%s/clusterprojection_%s.mat.npy" % (_basedir,current_app.config['CLUSTER_PROJECTION_PATH'], pcluster)
    try:
        projection = np.load(matrix_file)
    except Exeption,err:
        sys.stderr.write('Failed to load projection matrix for cluster %s (%s)'%(pclust,err))
    PaperVector = np.array(pvector)
    try:
        coords = np.dot(PaperVector,projection)
    except:
        coords = []
    return coords

def find_paper_cluster(pvec,bibc):
    '''
    Given a paper vector of normalized keyword frequencies, reduced to 100 dimensions, find out
    to which cluster this paper belongs
    '''
    try:
        res = db.session.query(Clusters).filter(Clusters.members.any(bibc)).one()
        cluster_data = json.dumps(result, cls=AlchemyEncoder)
    except:
        res = None
    if res:
        return cluster_data['cluster']

    min_dist = 9999
    res = db.session.query(Clusters).all()
    clusters = json.loads(json.dumps(res, cls=AlchemyEncoder))
    for entry in clusters:
        centroid = entry['centroid']
        dist = np.linalg.norm(pvec-np.array(centroid))
        if dist < min_dist:
            cluster = entry['cluster']
        min_dist = min(dist, min_dist)
    return str(cluster)

def find_closest_cluster_papers(pcluster,vec):
    '''
    Given a cluster and a paper (represented by its vector), which are the
    papers in the cluster closest to this paper?
    '''
    # Find the cluster info for the given cluster, in particular the cluster
    # members (identified by their bibcodes)
    cluster_info = db.session.query(Clusters).filter(Clusters.cluster==int(pcluster)).one()
    # For each cluster member, retrieve their lower dimensional coordinate tuple, so that
    # we can calculate the distance of the current papers (the coordinates are stored in
    # 'vec')
    SQL = "SELECT * FROM clustering WHERE bibcode IN (%s)" % ",".join(map(lambda a: "\'%s\'"%a,cluster_info.members))
    results = db.session.execute(SQL)
    distances = []
    for result in results:
        paper = result[1]
        pvect = np.array(result[4])
        distance = np.linalg.norm(pvect-vec)
        distances.append((paper,distance))
    # All distances have been recorded, now sort them by distance (ascending),
    # and return the appropriate amount
    d = sorted(distances, key=operator.itemgetter(1),reverse=False)
    return map(lambda a: a[0],d[:current_app.config['MAX_NEIGHBORS']])

def find_recommendations(G,remove=None):
    '''Given a set of papers (which is the set of closest papers within a given
    cluster to the paper for which recommendations are required), find recommendations.'''
    # Get all coreads by frequent readers who read any of the closest papers (stored in G). 
    # The coreads consist of frequencies of papers read just before, or just after the
    # paper in the closest papers.
    # The alsoreads are taken to be all the coreads taken together
    BeforeFreq = []
    AfterFreq  = []
    alsoreads  = []
    for paper in G:
        result = db.session.query(CoReads).filter(CoReads.bibcode == paper).first()
        if not result:
            continue
        BeforeFreq = merge_tuples(BeforeFreq, result.coreads['before'])
        AfterFreq  = merge_tuples(AfterFreq, result.coreads['after'])
        alsoreads += [x[0] for x in result.coreads['before']]
        alsoreads += [x[0] for x in result.coreads['after']]
    # remove (if specified) the paper for which we get recommendations
    if remove:
        alsoreads = filter(lambda a: a != remove, alsoreads)
    # calculate frequency distribution of alsoreads
    AlsoFreq  = get_frequencies(alsoreads)
    # get publication data for the top 100 most alsoread papers
    top100 = map(lambda a: a[0], AlsoFreq)
    top100_data = get_article_data(top100)
    # For publications with no citations, Solr docs don't have a citation count
    tmpdata = []
    for item in top100_data:
        if 'citation_count' not in item:
            item.update({'citation_count':0})
        tmpdata.append(item)
    top100_data = tmpdata
    mostRecent = top100_data[0]['bibcode']
    top100_data = sorted(top100_data, key=operator.itemgetter('citation_count'),reverse=True)
    # get the most cited paper from the top 100 most alsoread papers
    MostCited = top100_data[0]['bibcode']
    # get the most papers cited BY the top 100 most alsoread papers
    # sorted by citation
    refs100 = flatten(map(lambda a: a['reference'], top100_data))
    RefFreq = get_frequencies(refs100)
    # get the papers that cite the top 100 most alsoread papers
    # sorted by frequency
    cits100 = get_citing_papers(bibcodes=top100)
    CitFreq = get_frequencies(cits100)
    # now we have everything to build the recommendations
    FieldNames = 'Field definitions:'
    Recommendations = []
    Recommendations.append(FieldNames)
    Recommendations.append(G[0])
    Recommendations.append(BeforeFreq[0][0])
    if AfterFreq[0][0] == BeforeFreq[0][0]:
        try:
            Recommendations.append(AfterFreq[1][0])
        except:
            Recommendations.append(AfterFreq[0][0])
    else:
        Recommendations.append(AfterFreq[0][0])
    try:
        Recommendations.append(rndm.choice(AlsoFreq[:10])[0])
    except:
        Recommendations.append(AlsoFreq[0][0])
    Recommendations.append(mostRecent)
    try:
        Recommendations.append(rndm.choice(CitFreq[:10])[0])
    except:
        Recommendations.append(CitFreq[0][0])
    try:
        Recommendations.append(rndm.choice(RefFreq[:10])[0])
    except:
        Recommendations.append(RefFreq[0][0])
    Recommendations.append(MostCited)

    return Recommendations

# The actual recommending functions
def get_recommendations(bibcode):
    '''
    Recommendations for a single bibcode
    '''
    try:
        vec = make_paper_vector(bibcode)
    except Exception, e:
        raise Exception('make_paper_vector: failed to make paper vector (%s): %s' % (bibcode,str(e)))
    try:
        pvec = project_paper(vec)
    except Exception, e:
        raise Exception('project_paper: failed to project paper vector (%s): %s' % (bibcode,str(e)))
    try:
        pclust = find_paper_cluster(pvec,bibcode)
    except Exception, e:
        raise Exception('find_paper_cluster: failed to find cluster (%s): %s' % (bibcode,str(e)))
    try:
        cvec = project_paper(pvec,pcluster=pclust)
    except Exception, e:
        raise Exception('project_paper: failed to project %s within cluster %s: %s'%(bibcode,pclust, str(e)))
    try:
        close = find_closest_cluster_papers(pclust,cvec)
    except Exception, e:
        raise Exception('find_closest_cluster_papers: failed to find closest cluster papers (%s): %s'%(bibcode,str(e)))
    try:
        R = find_recommendations(close,remove=bibcode)
    except Exception, e:
        raise Exception('find_recommendations: failed to find recommendations. paper: %s, closest: %s, error: %s' % (bibcode,str(close),str(e)))
    # Get meta data for the recommendations
    try:
        meta_dict = get_article_data(R[1:], check_references=False)
    except Exception, e:
        raise Exception('get_article_data: failed to retrieve article data for recommendations (%s): %s'%(bibcode,str(e)))
    # Filter out any bibcodes for which no meta data was found
    recommendations = filter(lambda a: a in meta_dict, R)

    result = {'paper':bibcode,
              'recommendations':[{'bibcode':x,'title':meta_dict[x]['title'], 
              'author':meta_dict[x]['author']} for x in recommendations[1:]]}

    return result
