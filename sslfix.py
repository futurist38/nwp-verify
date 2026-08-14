# -*- coding: utf-8 -*-
"""
OS 인증서 저장소로 SSL 검증 (import만 하면 적용).

이 PC는 AVG 안티바이러스가 모든 HTTPS를 자체 루트 인증서로 가로채므로
certifi 번들만 신뢰하는 requests/urllib은 전 도메인에서
CERTIFICATE_VERIFY_FAILED가 난다 (2026-08-14 실측).
truststore는 Windows 인증서 저장소를 쓰므로 AVG 루트를 신뢰한다.
GitHub Actions(ubuntu)에서도 무해하게 동작한다.
"""
try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass
