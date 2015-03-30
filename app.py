import os
import time
from collections import OrderedDict

import boto
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
    distribution = status.distribution

    s3key = request.form['s3key']
    scheme = request.form.get('scheme', 'http') + '://'
    url = scheme + distribution.domain_name + '/' + s3key

    # Render a page to set the cookies and then redirect
    # to cf.
    response = current_app.make_response(
        render_template('redirect.html', url=url)
    )

    # Now set the cookies
    # Cloudfront key
    response.set_cookie(
        key='CloudFront-Key-Pair-Id',
        value=current_app.config['CLOUDFRONT_KEY_ID'],
        domain=distribution.domain_name,
    )

    return response


if __name__ == '__main__':
    app.run('0.0.0.0', debug=True)
