# -*- coding: utf-8 -*-
"""up2cos — store objects in Tencent Cloud COS.

Driver contract (v2): ``upimg_save(filename, stream, upload_path, backend=...)``
returns ``{"code": 0, "path": <cos key>, "size": <bytes>, "etag": <md5>}`` plus
``src`` when the backend declares a public ``domain``; without it the service
layer falls back to ``/raw/<sha>``.

``upimg_url`` signs a temporary read address so the same driver can back a
``private`` bucket: sapic relays the body itself and the signature never reaches
the browser.

Credentials come from ``backend["config"]`` (``bucket`` / ``region`` /
``secret_id`` / ``secret_key`` / ``basedir`` / ``domain`` / ``thumb_suffix``);
nothing is read from the site settings any more, so one driver can back several
buckets with different keys.

:copyright: (c) 2020 by staugur.
:license: BSD 3-Clause, see LICENSE for more details.
"""

from __future__ import annotations

import logging
from hashlib import sha256

try:  # pragma: no cover - optional dependency
    from qcloud_cos import CosConfig, CosS3Client
except ImportError:  # pragma: no cover - optional dependency
    CosConfig = CosS3Client = None

__version__ = '0.2.0'
__author__ = 'staugur <staugur@saintic.com>'
__description__ = '将图片保存到腾讯云'
__catalog__ = 'upload'
__state__ = 'disabled'
__appversion__ = '2.x'

logger = logging.getLogger(__name__)

FIELDS = (
    (
        'domain',
        'input',
        '加速域名',
        'COS 绑定的公有读加速域名；私有桶留空，由 sapic 的 /raw 转发读取',
    ),
    (
        'thumb_suffix',
        'input',
        '缩略图参数',
        '图片处理后缀，如 ?imageMogr2/thumbnail/400x；留空则列表页加载原图',
    ),
    ('bucket', 'input', 'Bucket', 'COS 存储桶名称，形如 test-1250000000'),
    (
        'region',
        'input',
        '地域',
        '存储桶所在地域，如 ap-beijing；留空则自动探测（需要列举存储桶权限）',
    ),
    (
        'secret_id',
        'password',
        'SecretId',
        '腾讯云 API 密钥的 SecretId，支持有 COS 管理权限的子用户',
    ),
    (
        'secret_key',
        'password',
        'SecretKey',
        '腾讯云 API 密钥的 SecretKey，子用户需勾选编程访问',
    ),
    ('basedir', 'input', '存储根目录', '图片存储到 COS 的基础目录，默认是根目录'),
)
REQUIRED = ('bucket', 'secret_id', 'secret_key')
#: Region used for service level requests such as ``list_buckets``.
DEFAULT_REGION = 'ap-beijing'
#: ``region`` is probed once per (secret_id, bucket) and kept in memory: a
#: private backend asks for a read address on every image view.
_REGION_CACHE = {}


def hook_manifest():
    return {
        'title': '腾讯云 COS',
        'catalog': 'upload',
        'config_schema': [
            {
                'type': kind,
                'key': key,
                'label': label,
                'placeholder': hint,
                'required': key in REQUIRED,
            }
            for key, kind, label, hint in FIELDS
        ],
        'actions': [
            {
                'name': 'ping',
                'label': '检查存储桶',
                'scope': 'admin',
                'with_form': True,
            }
        ],
        'slots': [{'name': 'admin.hook_setting'}],
    }


def slot_admin_hook_setting(context=None, **kwargs):
    backend = (context or {}).get('backend') or {}
    config = backend.get('config') or {}
    children = [
        {
            'type': kind,
            'key': key,
            'label': label,
            'help': hint,
            'default': config.get(key) or '',
            'required': key in REQUIRED,
        }
        for key, kind, label, hint in FIELDS
    ]
    children.append(
        {'type': 'button', 'text': '检查存储桶', 'action': 'ping', 'with_form': True}
    )
    if backend.get('in_use'):
        children.insert(
            0, {'type': 'alert', 'level': 'success', 'text': '当前正在使用'}
        )
    return [{'type': 'fieldset', 'legend': '腾讯云 COS', 'children': children}]


def _config(backend=None) -> dict:
    return (backend or {}).get('config') or {}


def _value(values, config, key) -> str:
    value = (values or {}).get(key)
    if value in (None, ''):
        value = (config or {}).get(key)
    return str(value or '').strip()


def _key(basedir, upload_path, filename) -> str:
    parts = []
    for part in (basedir, upload_path, filename):
        text = str(part or '').strip('/')
        if text:
            parts.append(text)
    return '/'.join(parts)


def _detect_region(config: dict) -> str:
    """Region of the configured bucket, empty when it cannot be probed."""
    bucket = str(config.get('bucket') or '').strip()
    secret_id = str(config.get('secret_id') or '').strip()
    secret_key = str(config.get('secret_key') or '').strip()
    cache_key = (secret_id, bucket)
    if cache_key in _REGION_CACHE:
        return _REGION_CACHE[cache_key]

    region = ''
    try:
        client = CosS3Client(
            CosConfig(
                Region=DEFAULT_REGION,
                SecretId=secret_id,
                SecretKey=secret_key,
            )
        )
        buckets = (client.list_buckets() or {}).get('Buckets', {}).get('Bucket') or []
        for item in buckets:
            if item.get('Name') == bucket:
                region = str(item.get('Location') or '').strip()
                break
    except Exception:
        logger.warning(
            'Failed to detect the region of COS bucket %s', bucket, exc_info=True
        )
    if region:
        _REGION_CACHE[cache_key] = region
    return region


def _client(config: dict):
    """Return ``(CosS3Client, "")`` or ``(None, error message)``."""
    if CosConfig is None:
        return None, 'Please install cos-python-sdk-v5 module'
    for key in REQUIRED:
        if not str(config.get(key) or '').strip():
            return None, 'The tencent %s parameter error' % key

    region = str(config.get('region') or '').strip() or _detect_region(config)
    if not region:
        return None, 'The tencent region parameter error'
    client = CosS3Client(
        CosConfig(
            Region=region,
            SecretId=str(config['secret_id']).strip(),
            SecretKey=str(config['secret_key']).strip(),
        )
    )
    return client, ''


def _bucket(config: dict) -> str:
    return str(config.get('bucket') or '').strip()


def _public_domain(config: dict, backend=None) -> str:
    """Direct link prefix; empty for a ``private`` backend.

    A private bucket rejects anonymous reads, so handing out ``src`` would give
    the browser a 403. The service layer ignores it, but per the driver contract
    the driver should not return one at all: private images are always served by
    ``/raw/<sha>`` through :func:`upimg_url`.
    """
    visibility = str((backend or {}).get('visibility') or '').strip().lower()
    if visibility == 'private':
        return ''
    return str(config.get('domain') or '').strip().rstrip('/')


def _status_of(exc) -> int:
    """HTTP status carried by a ``CosServiceError`` (or any SDK exception)."""
    for name in ('get_status_code', 'status_code', 'status'):
        attr = getattr(exc, name, None)
        if attr is None:
            continue
        if callable(attr):
            try:
                return int(attr())
            except (TypeError, ValueError):
                continue
        try:
            return int(attr)
        except (TypeError, ValueError):
            continue
    return 0


def upimg_save(filename, stream, upload_path='', backend=None, **kwargs):
    config = _config(backend)
    if not filename or stream is None:
        return {'code': 1, 'message': 'Parameter error'}
    client, error = _client(config)
    if error:
        return {'code': 1, 'message': error}

    data = stream if isinstance(stream, (bytes, bytearray)) else stream.read()
    key = _key(config.get('basedir'), upload_path, filename)
    try:
        response = client.put_object(
            Bucket=_bucket(config),
            Key=key,
            Body=data,
            EnableMD5=False,
        )
    except Exception as exc:
        return {'code': 1, 'message': str(exc)}

    etag = str((response or {}).get('ETag') or '').replace('"', '').strip()
    result = {
        'code': 0,
        'path': key,
        'size': len(data),
        'etag': etag or sha256(data).hexdigest()[:32],
    }
    #: 私有桶不给直链：读取一律走 /raw 的签名转发。
    domain = _public_domain(config, backend)
    if domain:
        result['src'] = '%s/%s' % (domain, key)
    return result


def upimg_url(save_result, filename='', backend=None, expires=300, **kwargs):
    """Signed GET address for a ``private`` bucket.

    Only called when the backend ``visibility`` is ``private``: sapic asks for a
    temporary address and relays the body itself, so neither the signature nor
    the credentials ever reach the browser. The signature is computed against
    the bucket origin (not the CDN domain), because a CDN usually ignores the
    query-string authorisation.
    """
    config = _config(backend)
    key = str((save_result or {}).get('path') or '').strip()
    if not key:
        return {'code': 1, 'message': 'The object key is required'}
    client, error = _client(config)
    if error:
        return {'code': 1, 'message': error}

    bucket = _bucket(config)
    seconds = int(expires or 300)
    try:
        url = client.get_presigned_url(
            Bucket=bucket, Key=key, Method='GET', Expired=seconds
        )
    except (AttributeError, TypeError):
        #: 老版本 SDK 只有 ``get_presigned_download_url``（或参数名不同）。
        try:
            url = client.get_presigned_download_url(
                Bucket=bucket, Key=key, Expired=seconds
            )
        except Exception as exc:
            return {'code': 1, 'message': str(exc)}
    except Exception as exc:
        return {'code': 1, 'message': str(exc)}
    return {'code': 0, 'url': url}


def upimg_delete(sha, upload_path, filename, basedir, save_result, backend=None, **kwargs):
    config = _config(backend)
    client, error = _client(config)
    if error:
        return {'code': 1, 'message': error}

    save_result = save_result or {}
    key = save_result.get('path') or _key(
        config.get('basedir') or basedir, upload_path, filename
    )
    if not key:
        return {'code': 1, 'message': 'The object key is required'}
    try:
        client.delete_object(Bucket=_bucket(config), Key=key)
    except Exception as exc:
        #: 失败不要抛：核心按 code 判定，抛出会打断同批次的其它副本删除。
        return {'code': 1, 'message': str(exc)}
    return {'code': 0}


def action_ping(values=None, context=None, **kwargs):
    config = ((context or {}).get('backend') or {}).get('config') or {}
    merged = {key: _value(values, config, key) for key, _, _, _ in FIELDS}
    client, error = _client(merged)
    if error:
        return {'code': 1, 'message': error}

    #: ``head_bucket`` 是桶级请求：任何异常都说明桶不可用（403 凭证/权限，
    #: 404 桶名，其它网络或地域错误），直接返回原因便于排查。
    try:
        client.head_bucket(Bucket=_bucket(merged))
    except Exception as exc:
        status = _status_of(exc)
        if status in (401, 403):
            return {'code': 1, 'message': 'invalid secret id, secret key or bucket'}
        return {'code': 1, 'message': str(exc)[:200]}
    return {'code': 0, 'toast': {'level': 'success', 'text': 'bucket is reachable'}}
