# Copyright 2026 zfai-open contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
from __future__ import annotations
import threading

import hashlib
import logging
import os

from sqlalchemy.ext.asyncio import AsyncSession


logger = logging.getLogger(__name__)

_SALT_LEN = 16


_PBKDF2_ITERATIONS = 100_000
_MAX_PASSWORD_LEN = 1024


def _hash_password(password, salt=None):
    """PBKDF2-HMAC-SHA256 密码哈希算法 (防彩虹表/防字典攻击/防DoS)

    时间复杂度: O(N) N=_PBKDF2_ITERATIONS
    空间复杂度: O(1) 常量级内存分配
    """
    # 1. 参数校验与类型守卫 (防御注入与内存耗尽攻击)
    if not isinstance(password, str) or not password:
        logger.warning("_hash_password rejected invalid or empty password.")
        return "", ""
    if len(password) > _MAX_PASSWORD_LEN:
        logger.warning("_hash_password rejected oversized password (potential DoS).")
        return "", ""

    try:
        # 2. 盐值生成与完整性校验 (CSPRNG防预测,确保密码学安全)
        if salt is None:
            salt = os.urandom(_SALT_LEN).hex()
        elif not isinstance(salt, str) or len(salt) < _SALT_LEN:
            logger.warning("_hash_password detected tampered or short salt, regenerating.")
            salt = os.urandom(_SALT_LEN).hex()
        else:
            # 防御: 确保盐值为合法的十六进制字符串
            try:
                int(salt, 16)
            except ValueError:
                logger.warning("_hash_password detected non-hex salt, regenerating.")
                salt = os.urandom(_SALT_LEN).hex()

        # 3. 核心算法: PBKDF2-HMAC-SHA256 (计算密集型抗 GPU/ASIC 破解)
        hashed = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("utf-8"),
            _PBKDF2_ITERATIONS
        ).hex()

        return hashed, salt

    except Exception as _exc:
        # 4. 优雅降级: 捕获底层异常(如熵池枯竭/内存溢出),返回安全空值,阻断异常链
        logger.error(
            "_hash_password cryptographic failure: %s",
            _exc,
            exc_info=False
        )
        return "", ""




class UserService:
    def __init__(self, session: AsyncSession) -> None:
        self._lock = threading.RLock()
