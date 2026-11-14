up2cos
========

这是基于 `sapic <https://github.com/staugur/sapic>`_ 图床（v2）的一个扩展模块，
用来将上传的图片保存到腾讯云
`对象存储(COS) <https://cloud.tencent.com/product/cos>`_。

- 钩子名（模块名）：``up2cos``
- 扩展类型：``upload``（存储驱动）
- 适用版本：sapic 2.x（V1 的 ``g.cfg`` / ``intpl_localhooksetting`` 契约已废弃）

安装
-----

- 正式版本

    ``$ pip install -U up2cos``

- 开发版本

    ``$ pip install -U git+https://github.com/staugur/picbed-up2cos.git@master``

依赖 ``cos-python-sdk-v5``；未安装时钩子仍能加载，只是上传会返回
``Please install cos-python-sdk-v5 module``。

开始使用
---------

添加：
^^^^^^

在 **站点管理-钩子插件** 中导入模块名 ``up2cos``（或 ``POST /api/v2/hooks/import``），
然后启用它。启用后 sapic 会自动创建一条同名存储后端。

配置：
^^^^^^

在 **站点管理-存储后端** 里为该后端填写（不是旧的“网站设置”）：

- ``bucket``（必填）：COS 存储桶名称，形如 ``test-1250000000``
- ``secret_id``（必填）：腾讯云 API 密钥 SecretId，可用有 COS 管理权限的子用户
- ``secret_key``（必填）：腾讯云 API 密钥 SecretKey，子用户需勾选“编程访问”
- ``region``：地域，如 ``ap-beijing``；留空则自动探测（需要列举存储桶权限）
- ``domain``：公有读加速域名；留空则由 sapic 的 ``/raw/<sha>`` 代理输出
- ``basedir``：存储根目录，默认桶根目录
- ``thumb_suffix``：缩略图参数，如 ``?imageMogr2/thumbnail/400x``

填好后可点「检查存储桶」验证凭证与桶是否可达。

同一个驱动可以建多条存储后端（不同桶、不同密钥、不同优先级），上传走优先级
最高的那条，其余作为异步副本；判断依据是后端行的 ``priority``（数值越小越优先）。

私有桶（签名读）：
^^^^^^^^^^^^^^^^^^

桶为私有读时，把后端的「访问方式」设为 ``private`` 即可，``domain`` 可留空：

- 本驱动实现了 ``upimg_url``，后台不会再报 ``driver cannot read private objects``；
- 图片直链固定为 ``/raw/<sha>``，sapic 请求本驱动签发 ``get_presigned_url`` 的临时
  地址（有效期由核心决定，默认 300 秒），在服务端拉取并流式转发，签名与密钥都不
  会出现在浏览器；
- 签名针对 COS 源站（``{bucket}.cos.{region}.myqcloud.com``），不针对 CDN 域名；
- ``private`` 后端不再返回 ``src``，需要 CDN 直链的可同时建一个 ``public`` 后端副本。

V1 升级提示
------------

V2 的配置存在存储后端行里，V1 站点设置中的 ``tencent_*`` 不会自动迁移，需要重新
填写一次；已上传图片的记录与旧直链不受影响。
