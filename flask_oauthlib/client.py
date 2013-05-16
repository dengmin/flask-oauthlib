# coding: utf-8
"""
Flask-OAuthlib
--------------

Implemnts OAuth1 and OAuth2 support for Flask.

:copyright: (c) 2013 by Hsiaoming Yang.
"""

import urllib2
import oauthlib.oauth1
import oauthlib.oauth2
from oauthlib.common import to_unicode
from urlparse import urljoin
from flask import request, redirect, json, session
from werkzeug import url_quote, url_decode, parse_options_header


class OAuth(object):
    """Registry for remote applications.

    :param app: the app instance of Flask

    Create an instance with Flask::

        oauth = OAuth(app)
    """

    def __init__(self, app=None):
        self.remote_apps = {}

        if app:
            self.init_app(app)

    def init_app(self, app):
        """
        You can also pass the instance of Flask later::

            oauth = OAuth()
            oauth.init_app(app)
        """

        self.app = app
        app.extensions = getattr(app, 'extensions', {})
        app.extensions['oauth-client'] = self

    def remote_app(self, name, register=True, **kwargs):
        """Registers a new remote application.

        :param name: the name of the remote application
        :param register: whether the remote app will be registered
        :param base_url: the base url for every request
        :param request_token_url: the url for requesting new tokens
        :param access_token_url: the url for token exchange
        :param authorize_url: the url for authorization
        :param consumer_key: the application specific consumer key
        :param consumer_secret: the application specific consumer secret
        :param request_token_params: an optional dictionary of parameters
                                     to forward to the request token url
                                     or authorize url depending on oauth
                                     version
        :param access_token_params: an optional dictionary of parameters to
                                    forward to the access token url
        :param access_token_method: the HTTP method that should be used for
                                    the access_token_url. Default is ``GET``
        """

        app = OAuthRemoteApp(self, name, **kwargs)
        if register:
            assert name not in self.remote_apps
            self.remote_apps[name] = app
        return app

    def __getattr__(self, key):
        try:
            return object.__getattribute__(self, key)
        except AttributeError:
            app = self.remote_apps.get(key)
            if app:
                return app
            raise AttributeError('No such app: %s' % key)


_etree = None


def get_etree():
    global _etree
    if _etree is not None:
        return _etree
    try:
        from lxml import etree as _etree
    except ImportError:
        try:
            from xml.etree import cElementTree as _etree
        except ImportError:
            try:
                from xml.etree import ElementTree as _etree
            except ImportError:
                raise TypeError('lxml or etree not found')
    return _etree


def parse_response(resp, content, strict=False, content_type=None):
    content_type = resp.headers.get('content-type', content_type)
    ct, options = parse_options_header(content_type)

    if ct in ('application/json', 'text/javascript'):
        return json.loads(content)

    if ct in ('application/xml', 'text/xml'):
        charset = options.get('charset', 'utf-8')
        return get_etree().fromstring(content.decode(charset))

    if ct != 'application/x-www-form-urlencoded':
        if strict:
            return content
    charset = options.get('charset', 'utf-8')
    return url_decode(content, charset=charset).to_dict()


class OAuthException(RuntimeError):
    def __init__(self, message, type=None, data=None):
        self.message = message
        self.type = type
        self.data = data

    def __str__(self):
        return self.message.encode('utf-8')

    def __unicode__(self):
        return self.message


class OAuthRemoteApp(object):
    """Represents a remote application.

    :param oauth: the associated :class:`OAuth` object
    :param name: the name of the remote application
    :param base_url: the base url for every request
    :param request_token_url: the url for requesting new tokens
    :param access_token_url: the url for token exchange
    :param authorize_url: the url for authorization
    :param consumer_key: the application specific consumer key
    :param consumer_secret: the application specific consumer secret
    :param request_token_params: an optional dictionary of parameters
                                 to forward to the request token url
                                 or authorize url depending on oauth
                                 version
    :param access_token_params: an optional dictionary of parameters to
                                forward to the access token url
    :param access_token_method: the HTTP method that should be used for
                                the access_token_url. Default is ``GET``
    """
    def __init__(
        self, oauth, name,
        base_url, request_token_url,
        access_token_url, authorize_url,
        consumer_key, consumer_secret,
        request_token_params=None,
        access_token_params=None,
        access_token_method='GET',
        encoding='utf-8',
    ):

        self.oauth = oauth
        self.base_url = base_url
        self.name = name
        self.request_token_url = request_token_url
        self.access_token_url = access_token_url
        self.authorize_url = authorize_url
        self.consumer_key = consumer_key
        self.consumer_secret = consumer_secret
        self.request_token_params = request_token_params or {}
        self.access_token_params = access_token_params or {}
        self.access_token_method = access_token_method
        self.encoding = encoding

        # request_token_url is for oauth1
        if request_token_url:
            self._client = oauthlib.oauth1.Client(
                consumer_key, consumer_secret
            )
        else:
            self._client = oauthlib.oauth2.WebApplicationClient(consumer_key)

    def expand_url(self, url):
        return urljoin(self.base_url, url)

    def generate_request_token(self, callback=None):
        # for oauth1 only
        if callback is not None:
            callback = urljoin(request.url, callback)
        self._client.callback_uri = _encode(callback, self.encoding)
        uri, headers, _ = self._client.sign(
            self.expand_url(self.request_token_url)
        )
        req = urllib2.Request(uri, headers=headers)
        resp = urllib2.urlopen(req)
        if resp.code not in (200, 201):
            raise OAuthException(
                'Failed to generate request token',
                type='token_generation_failed'
            )
        content = resp.read()
        resp.close()
        data = parse_response(resp, content)
        if data is None:
            raise OAuthException(
                'Invalid token response from %s' % self.name,
                type='token_generation_failed'
            )
        tup = (data['oauth_token'], data['oauth_token_secret'])
        session['%s_oauthtok'] = tup
        return tup

    def make_client(self, token=None):
        pass

    def authorize(self, callback=None):
        if self.request_token_url:
            token = self.generate_request_token(callback)[0]
            url = '%s?oauth_token=%s' % (
                self.expand_url(self.authorize_url), url_quote(token)
            )
        else:
            assert callback is not None, 'Callback is required OAuth2'

        return redirect(url)

    def tokengetter(self, f):
        """
        Register a function as token getter.
        """
        self.tokengetter_func = f
        return f

    def handle_oauth1_response(self):
        pass

    def handle_oauth2_response(self):
        pass


def _encode(text, encoding='utf-8'):
    if encoding:
        return to_unicode(text, encoding)
    return text


# some common services
twitter_urls = dict(
    base_url='https://api.twitter.com/1/',
    request_token_url='https://api.twitter.com/oauth/request_token',
    access_token_url='https://api.twitter.com/oauth/access_token',
    authorize_url='https://api.twitter.com/oauth/authenticate',
)
facebook_urls = dict(
    base_url='https://graph.facebook.com',
    request_token_url=None,
    access_token_url='/oauth/access_token',
    authorize_url='https://www.facebook.com/dialog/oauth'
)
google_urls = dict(
    base_url='https://www.google.com/accounts/',
    authorize_url='https://accounts.google.com/o/oauth2/auth',
    request_token_url=None,
    access_token_url='https://accounts.google.com/o/oauth2/token',
)
weibo_urls = dict(
)
douban_urls = dict(
)