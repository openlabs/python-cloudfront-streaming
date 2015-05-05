import os
import time
from collections import OrderedDict

import boto
from boto.cloudfront.distribution import Distribution
from flask import Flask, render_template, current_app, request, redirect

app = Flask(__name__)
app.config.from_envvar('CFTEST_SETTINGS')


class StatusCheck(object):
    """
    An object that returns the stats about the access to S3
    """
    _s3conn = None
    _cfconn = None
    _config_cleared = None

    config_parameters = OrderedDict([
        ('access_key_defined', 'AWS Access Key defined in config'),
        ('secret_key_defined', 'AWS Secret Key defined in config'),
        ('s3_bucket_defined', 'S3 bucket defined in config'),
        ('distribution_defined', 'Distribution defined in config'),
        ('cf_key_id_defined', 'Signing private key defined'),
        ('private_key', 'Private key file defined and exists ?'),
    ])
    connection_parameters = OrderedDict([
        ('access_bucket', 'Has Access to bucket'),
        ('access_distribution', 'Has Access to distribution'),
    ])
    signed_cookie_parameters = OrderedDict([
        ('domain_defined', 'CF Domain/CNAME Defined'),
        ('cookie_domain_defined', 'Cookie Domain defined'),
    ])

    @property
    def access_key_defined(self):
        if current_app.config['ACCESS_KEY']:
            return True
        self._config_cleared = False

    @property
    def secret_key_defined(self):
        if current_app.config['SECRET_KEY']:
            return True
        self._config_cleared = False

    @property
    def s3_bucket_defined(self):
        if current_app.config['S3_BUCKET']:
            return True
        self._config_cleared = False

    @property
    def distribution_defined(self):
        if current_app.config['DISTRIBUTION']:
            return True
        self._config_cleared = False

    @property
    def domain_defined(self):
        if current_app.config['DOMAIN']:
            return True

    @property
    def cookie_domain_defined(self):
        if current_app.config['COOKIE_DOMAIN']:
            return True

    @property
    def cf_key_id_defined(self):
        if current_app.config['CLOUDFRONT_KEY_ID']:
            return True
        self._config_cleared = False

    @property
    def private_key(self):
        keyfile = current_app.config['PRIVATE_KEY_FILE']
        if keyfile and os.path.exists(keyfile):
            return True
        self._config_cleared = False

    @property
    def s3_connection(self):
        if self._s3conn is None:
            self._s3conn = boto.connect_s3(
                current_app.config['ACCESS_KEY'],
                current_app.config['SECRET_KEY'],
            )
        return self._s3conn

    @property
    def cf_connection(self):
        if self._cfconn is None:
            self._cfconn = boto.connect_cloudfront(
                current_app.config['ACCESS_KEY'],
                current_app.config['SECRET_KEY'],
            )
        return self._cfconn

    @property
    def bucket(self):
        return self.s3_connection.get_bucket(
            current_app.config['S3_BUCKET']
        )

    @property
    def distribution(self):
        return self.cf_connection.get_distribution_info(
            current_app.config['DISTRIBUTION']
        )

    @property
    def domain(self):
        if current_app.config['DOMAIN']:
            return current_app.config['DOMAIN']
        return None

    @property
    def cookie_domain(self):
        if current_app.config['COOKIE_DOMAIN']:
            return current_app.config['COOKIE_DOMAIN']
        return None

    @property
    def access_distribution(self):
        try:
            self.distribution
        except Exception as e:
            print e
            self._config_cleared = False
            return False
        else:
            return True

    @property
    def access_bucket(self):
        try:
            self.bucket
        except Exception as e:
            print e
            self._config_cleared = False
            return False
        else:
            return True


status = StatusCheck()


@app.route('/')
def index():
    """
    The homepage
    """
    return render_template(
        'index.html', status=status
    )


@app.route('/generate-signed-url', methods=['POST'])
def generate_signed_url():
    """
    Generate a signed URL and redirect to signed URL
    """
    distribution = status.distribution

    s3key = request.form['s3key']
    scheme = request.form.get('scheme', 'http') + '://'
    url = scheme + distribution.domain_name + '/' + s3key

    return redirect(
        distribution.create_signed_url(
            url,
            current_app.config['CLOUDFRONT_KEY_ID'],
            policy_url=scheme + distribution.domain_name + '/*',
            expire_time=int(time.time()) + 60 * 60,
            private_key_file=current_app.config['PRIVATE_KEY_FILE']
        )
    )


@app.route('/test-video-streaming', methods=['GET'])
def video_streaming_test():
    """
    Renders a video using flowplayer
    """
    distribution = status.distribution

    s3key = 'video.mp4'
    scheme = 'https://'
    url = scheme + distribution.domain_name + '/' + s3key

    url = distribution.create_signed_url(
        url,
        current_app.config['CLOUDFRONT_KEY_ID'],
        policy_url=scheme + distribution.domain_name + '/*',
        expire_time=int(time.time()) + 60 * 60,
        private_key_file=current_app.config['PRIVATE_KEY_FILE']
    )
    return render_template('video.html', url=url)


@app.route('/generate-signed-cookie', methods=['POST'])
def generate_signed_cookie():
    """
    Drop a signed cookie and then redirect to URL
    """
    resource = request.form.get('resource') or request.form['s3key']
    secure = request.form['scheme'] == 'https'

    distribution = SignedCookiedCloudfrontDistribution(
        status.distribution, status.domain
    )
    cookies = distribution.create_signed_cookies(
        resource,
        current_app.config['PRIVATE_KEY_FILE'],
        current_app.config['CLOUDFRONT_KEY_ID'],
        expire_minutes=60,
        secure=secure
    )

    # Build a response that redirects
    url = distribution.get_http_resource_url(
        request.form['s3key'], secure=secure
    )
    response = current_app.make_response(
        render_template('redirect.html', url=url)
    )

    for key, value in cookies.iteritems():
        response.set_cookie(
            key=key,
            value=value,
            domain=status.cookie_domain,
        )

    return response


class SignedCookiedCloudfrontDistribution(object):
    """
    Based on the example at:
    https://stackoverflow.com/questions/29383373/creating-signed-cookies-for-amazon-cloudfront
    """

    def __init__(self, distribution, domain=None):
        """
        :param distribution: Cloudfront Distribution object from boto
        :param domain:  The domain to use when generating the URL for the
                        object. Specify this only if there is a cname you are
                        using, that maps to the distribution.
                        If nothing is specified, the default is distribtuion's
                        domain
        """
        self.distribution = distribution
        self.domain = domain if domain else distribution.domain_name

    def get_http_resource_url(self, resource, secure):
        """
        :param resource: path and/or filename to the resource
                         (e.g. /mydir/somefile.txt);
        :param secure: use https or http protocol for Cloudfront URL - update
                       to match your distribution settings.
        :return: constructed URL
        """
        scheme = "http" if not secure else "https"
        return '%s://%s/%s' % (scheme, self.domain, resource)

    def create_signed_cookies(
            self, resource, private_key_file, key_pair_id,
            expire_minutes=3, secure=False):
        """
        generate the Cloudfront download distirbution signed cookies

        :param resource: The object or path of resource.
                         Examples: 'dir/object.mp4', 'dir/*', '*'
        :param private_key_file: Path to the private key file (pem encoded)
        :param key_pair_id: ID of the keypair used to sign the cookie
        :param expire_minutes:  The number of minutes until expiration
        :param secure: use https or http protocol for Cloudfront URL - update
                       to match your distribution settings.
        :return: Cookies to be set
        """
        http_resource = self.get_http_resource_url(resource, secure=secure)

        # generate no-whitespace json policy,
        # then base64 encode & make url safe
        policy = Distribution._canned_policy(
            http_resource,
            self.get_expires(expire_minutes)
        )
        encoded_policy = Distribution._url_base64_encode(policy)

        # assemble the 3 Cloudfront cookies
        signature = self.generate_signature(
            policy, private_key_file=private_key_file
        )
        cookies = {
            "CloudFront-Policy": encoded_policy,
            "CloudFront-Signature": signature,
            "CloudFront-Key-Pair-Id": key_pair_id
        }
        return cookies

    @staticmethod
    def get_expires(minutes):
        unixTime = time.time() + (minutes * 60)
        expires = int(unixTime)
        return expires

    @staticmethod
    def generate_signature(policy, private_key_file=None):
        """
        :param policy: no-whitespace json str (NOT encoded yet)
        :param private_key_file: your .pem file with which to sign the policy
        :return: encoded signature for use in cookie
        """
        # Distribution._create_signing_params()
        signature = Distribution._sign_string(policy, private_key_file)

        # now base64 encode the signature & make URL safe
        encoded_signature = Distribution._url_base64_encode(signature)

        return encoded_signature


if __name__ == '__main__':
    app.run('0.0.0.0', debug=True)
