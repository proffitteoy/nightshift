from __future__ import annotations

import base64
import hashlib
import hmac
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Optional
from urllib.parse import quote

import requests


DEFAULT_DM_ENDPOINT = "dm.aliyuncs.com"
DEFAULT_DM_REGION_ID = "cn-hangzhou"
DEFAULT_DM_API_VERSION = "2015-11-23"
DEFAULT_DM_ACTION = "SingleSendMail"
DEFAULT_DM_FORMAT = "JSON"
DEFAULT_DM_SIGNATURE_METHOD = "HMAC-SHA1"
DEFAULT_DM_SIGNATURE_VERSION = "1.0"


class EmailClientError(RuntimeError):
    pass


@dataclass(frozen=True)
class EmailClientConfig:
    access_key_id: str
    access_key_secret: str
    account_name: str
    region_id: str = DEFAULT_DM_REGION_ID
    endpoint: str = DEFAULT_DM_ENDPOINT
    address_type: int = 1
    reply_to_address: bool = False
    from_alias: str = ""
    connect_timeout_ms: int = 5000
    read_timeout_ms: int = 10000


class EmailClient:
    def __init__(self, session: Optional[requests.Session] = None) -> None:
        self._session = session or requests.Session()

    def send_html_email(
        self,
        config: EmailClientConfig,
        to_address: str,
        subject: str,
        html_body: str,
    ) -> Dict[str, object]:
        normalized_to = to_address.strip()
        normalized_subject = subject.strip()
        normalized_body = html_body.strip()
        if not normalized_to or not normalized_subject or not normalized_body:
            raise EmailClientError("to_address, subject and html_body are required")

        params = self._build_rpc_params(
            config=config,
            to_address=normalized_to,
            subject=normalized_subject,
            html_body=normalized_body,
        )
        signed_params = dict(params)
        signed_params["Signature"] = self._sign_rpc_params(params=params, access_key_secret=config.access_key_secret)

        try:
            response = self._session.post(
                self._build_endpoint_url(config.endpoint),
                data=signed_params,
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                timeout=(
                    max(config.connect_timeout_ms, 1000) / 1000.0,
                    max(config.read_timeout_ms, 1000) / 1000.0,
                ),
            )
        except requests.RequestException as exc:
            raise EmailClientError(f"Alibaba Cloud Direct Mail request failed: {exc}") from exc

        payload = self._parse_response_payload(response)
        if response.ok and not payload.get("Code"):
            return payload

        error_code = str(payload.get("Code", "")).strip() or f"HTTP_{response.status_code}"
        error_message = str(payload.get("Message", "")).strip() or "Alibaba Cloud Direct Mail request failed"
        request_id = str(payload.get("RequestId", "")).strip()
        detail = f"{error_code}: {error_message}"
        if request_id:
            detail += f" request_id={request_id}"
        raise EmailClientError(detail)

    def _build_rpc_params(
        self,
        *,
        config: EmailClientConfig,
        to_address: str,
        subject: str,
        html_body: str,
    ) -> Dict[str, str]:
        params = {
            "AccessKeyId": config.access_key_id,
            "Action": DEFAULT_DM_ACTION,
            "AccountName": config.account_name,
            "AddressType": str(int(config.address_type)),
            "Format": DEFAULT_DM_FORMAT,
            "HtmlBody": html_body,
            "RegionId": config.region_id,
            "ReplyToAddress": "true" if config.reply_to_address else "false",
            "SignatureMethod": DEFAULT_DM_SIGNATURE_METHOD,
            "SignatureNonce": uuid.uuid4().hex,
            "SignatureVersion": DEFAULT_DM_SIGNATURE_VERSION,
            "Subject": subject,
            "Timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "ToAddress": to_address,
            "Version": DEFAULT_DM_API_VERSION,
        }
        normalized_alias = config.from_alias.strip()
        if normalized_alias:
            params["FromAlias"] = normalized_alias
        return params

    def _sign_rpc_params(self, *, params: Dict[str, str], access_key_secret: str) -> str:
        canonicalized = "&".join(
            f"{self._percent_encode(key)}={self._percent_encode(value)}"
            for key, value in sorted(params.items(), key=lambda item: item[0])
        )
        string_to_sign = f"POST&%2F&{self._percent_encode(canonicalized)}"
        signature = hmac.new(
            f"{access_key_secret}&".encode("utf-8"),
            string_to_sign.encode("utf-8"),
            hashlib.sha1,
        ).digest()
        return base64.b64encode(signature).decode("utf-8")

    def _parse_response_payload(self, response: requests.Response) -> Dict[str, object]:
        text = response.text.strip()
        if not text:
            return {}
        try:
            payload = response.json()
        except ValueError:
            return {"Message": text[:500]}
        return payload if isinstance(payload, dict) else {"Message": json.dumps(payload, ensure_ascii=False)}

    def _build_endpoint_url(self, endpoint: str) -> str:
        normalized = endpoint.strip() or DEFAULT_DM_ENDPOINT
        if normalized.startswith("http://") or normalized.startswith("https://"):
            return normalized.rstrip("/") + "/"
        return f"https://{normalized.strip('/')}/"

    def _percent_encode(self, value: object) -> str:
        return quote(str(value), safe="~")
