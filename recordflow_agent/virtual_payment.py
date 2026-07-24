from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from dataclasses import dataclass, field
from typing import Any

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


PAYMENT_MODE = "short_series_goods"
PAYMENT_ENV = 0
PAYMENT_CURRENCY = "CNY"
DELIVERY_EVENT = "xpay_goods_deliver_notify"


class VirtualPaymentConfigurationError(RuntimeError):
    pass


class VirtualPaymentNotificationError(ValueError):
    pass


@dataclass(frozen=True)
class VirtualProduct:
    product_id: str
    points: int
    amount_cents: int
    label: str

    def public_dict(self) -> dict[str, int | str]:
        return {
            "product_id": self.product_id,
            "points": self.points,
            "amount_cents": self.amount_cents,
            "label": self.label,
        }


PRODUCTS = (
    VirtualProduct("dot_100", 100, 99, "100 点"),
    VirtualProduct("dot_500", 500, 499, "500 点"),
    VirtualProduct("dot_1000", 1000, 999, "1000 点"),
)
PRODUCTS_BY_POINTS = {product.points: product for product in PRODUCTS}
PRODUCTS_BY_ID = {product.product_id: product for product in PRODUCTS}


@dataclass(frozen=True)
class VirtualPaymentSettings:
    appid: str
    offer_id: str
    appkey: str = field(repr=False)
    mode: str = PAYMENT_MODE
    env: int = PAYMENT_ENV

    @classmethod
    def from_env(cls) -> VirtualPaymentSettings:
        mode = os.getenv("WECHAT_VIRTUAL_MODE", PAYMENT_MODE).strip()
        if mode != PAYMENT_MODE:
            raise VirtualPaymentConfigurationError(
                f"WECHAT_VIRTUAL_MODE must be {PAYMENT_MODE}"
            )
        appid = os.getenv("WECHAT_MINIAPP_APPID", "").strip()
        offer_id = os.getenv("WECHAT_VIRTUAL_OFFER_ID", "").strip()
        appkey = os.getenv("WECHAT_VIRTUAL_PRODUCTION_APPKEY", "").strip()
        if (
            not appid
            or not offer_id
            or len(appkey) != 32
            or not appkey.isalnum()
        ):
            raise VirtualPaymentConfigurationError(
                "production virtual-payment credentials are incomplete"
            )
        return cls(appid=appid, offer_id=offer_id, appkey=appkey)


@dataclass(frozen=True)
class VirtualPaymentNotificationSettings:
    appid: str
    offer_id: str
    token: str = field(repr=False)
    aes_key: str = field(repr=False)

    @classmethod
    def from_env(cls) -> VirtualPaymentNotificationSettings:
        appid = os.getenv("WECHAT_MINIAPP_APPID", "").strip()
        offer_id = os.getenv("WECHAT_VIRTUAL_OFFER_ID", "").strip()
        token = os.getenv("WECHAT_VIRTUAL_NOTIFY_TOKEN", "").strip()
        aes_key = os.getenv("WECHAT_VIRTUAL_NOTIFY_AES_KEY", "").strip()
        if (
            not appid
            or not offer_id
            or not 3 <= len(token) <= 32
            or not token.isalnum()
            or len(aes_key) != 43
            or not aes_key.isalnum()
        ):
            raise VirtualPaymentConfigurationError(
                "virtual-payment notification credentials are incomplete"
            )
        return cls(appid=appid, offer_id=offer_id, token=token, aes_key=aes_key)


@dataclass(frozen=True)
class VirtualPaymentNotification:
    out_trade_no: str
    transaction_id: str
    openid: str
    env: int
    product_id: str = ""
    offer_id: str = ""
    quantity: int | None = None
    amount_cents: int | None = None


def get_product(points: int) -> VirtualProduct | None:
    return PRODUCTS_BY_POINTS.get(int(points))


def build_payment_parameters(
    *,
    settings: VirtualPaymentSettings,
    product: VirtualProduct,
    session_key: str,
    out_trade_no: str,
) -> dict[str, Any]:
    sign_payload = {
        "mode": settings.mode,
        "offerId": settings.offer_id,
        "productId": product.product_id,
        "buyQuantity": 1,
        "goodsPrice": product.amount_cents,
        "currencyType": PAYMENT_CURRENCY,
        "env": settings.env,
        "outTradeNo": out_trade_no,
    }
    sign_data = json.dumps(sign_payload, ensure_ascii=False, separators=(",", ":"))
    pay_sig = hmac.new(
        settings.appkey.encode(),
        ("requestVirtualPayment&" + sign_data).encode(),
        hashlib.sha256,
    ).hexdigest()
    signature = hmac.new(
        session_key.encode(), sign_data.encode(), hashlib.sha256
    ).hexdigest()
    return {
        **sign_payload,
        "attach": json.dumps({"points": product.points}, separators=(",", ":")),
        "paySig": pay_sig,
        "signature": signature,
        "signData": sign_data,
    }


def verify_wechat_signature(token: str, signature: str, *parts: str) -> bool:
    if not signature:
        return False
    expected = hashlib.sha1(
        "".join(sorted([token, *parts])).encode("utf-8")
    ).hexdigest()
    return hmac.compare_digest(signature, expected)


def decrypt_wechat_envelope(encrypted: str, encoding_aes_key: str, appid: str) -> str:
    try:
        key_padding = "=" * (-len(encoding_aes_key) % 4)
        raw_key = base64.b64decode(encoding_aes_key + key_padding, validate=True)
        ciphertext = base64.b64decode(encrypted, validate=True)
        if len(raw_key) != 32 or not ciphertext or len(ciphertext) % 16:
            raise ValueError("invalid key or ciphertext length")
        decryptor = Cipher(algorithms.AES(raw_key), modes.CBC(raw_key[:16])).decryptor()
        padded = decryptor.update(ciphertext) + decryptor.finalize()
        pad = padded[-1]
        if pad < 1 or pad > 32 or padded[-pad:] != bytes([pad]) * pad:
            raise ValueError("invalid PKCS7 padding")
        plain = padded[:-pad]
        if len(plain) < 20:
            raise ValueError("decrypted message is too short")
        message_length = int.from_bytes(plain[16:20], "big")
        message_end = 20 + message_length
        if message_end > len(plain):
            raise ValueError("invalid message length")
        message_appid = plain[message_end:].decode("utf-8")
        if message_appid != appid:
            raise ValueError("appid mismatch")
        return plain[20:message_end].decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        raise VirtualPaymentNotificationError(str(exc)) from exc


def decrypt_wechat_notification(
    encrypted: str, encoding_aes_key: str, appid: str
) -> dict[str, Any]:
    message = decrypt_wechat_envelope(encrypted, encoding_aes_key, appid)
    try:
        payload = json.loads(message)
    except json.JSONDecodeError as exc:
        raise VirtualPaymentNotificationError("notification is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise VirtualPaymentNotificationError("notification must be a JSON object")
    return payload


def parse_payment_notification(event: dict[str, Any]) -> VirtualPaymentNotification | None:
    event_type = str(_find_value(event, {"event"}, recursive=False) or "").strip().lower()
    if event_type != DELIVERY_EVENT:
        return None

    out_trade_no = _required_text(event, {"outtradeno", "orderid", "orderno"}, "OutTradeNo")
    transaction_id = _required_text(
        event, {"transactionid", "tradeno", "transactionno"}, "TransactionId"
    )
    openid = _required_text(event, {"openid"}, "OpenId")
    env = _required_int(event, {"env"}, "Env")
    if env != PAYMENT_ENV:
        raise VirtualPaymentNotificationError("notification is not from production")

    return VirtualPaymentNotification(
        out_trade_no=out_trade_no,
        transaction_id=transaction_id,
        openid=openid,
        env=env,
        product_id=_optional_text(event, {"productid", "goodsid"}),
        offer_id=_optional_text(event, {"offerid"}),
        quantity=_optional_int(event, {"buyquantity", "quantity", "goodsnum"}),
        amount_cents=_optional_int(
            event, {"goodsprice", "amountcents", "payamount", "paidfee"}
        ),
    )


def validate_payment_notification(
    notification: VirtualPaymentNotification,
    *,
    order: dict[str, Any],
    settings: VirtualPaymentNotificationSettings,
    expected_openid: str,
) -> None:
    if order.get("provider") != "wechat_virtual":
        raise VirtualPaymentNotificationError("payment provider does not match")
    if int(order.get("environment", PAYMENT_ENV)) != PAYMENT_ENV:
        raise VirtualPaymentNotificationError("stored payment order is not production")
    if not expected_openid or notification.openid != expected_openid:
        raise VirtualPaymentNotificationError("payment user does not match")
    if order.get("offer_id") and order["offer_id"] != settings.offer_id:
        raise VirtualPaymentNotificationError("stored payment offer does not match")
    if notification.offer_id and notification.offer_id != settings.offer_id:
        raise VirtualPaymentNotificationError("payment offer does not match")

    product_id = str(order.get("product_id") or notification.product_id or "")
    product = PRODUCTS_BY_ID.get(product_id)
    if product is None:
        raise VirtualPaymentNotificationError("payment product does not exist")
    if notification.product_id and notification.product_id != product.product_id:
        raise VirtualPaymentNotificationError("payment product does not match")
    if (
        int(order.get("points", 0)) != product.points
        or int(order.get("amount_cents", 0)) != product.amount_cents
    ):
        raise VirtualPaymentNotificationError("stored payment product metadata does not match")
    if notification.quantity is not None and notification.quantity != 1:
        raise VirtualPaymentNotificationError("payment quantity does not match")
    if (
        notification.amount_cents is not None
        and notification.amount_cents != product.amount_cents
    ):
        raise VirtualPaymentNotificationError("payment amount does not match")


def _required_text(event: object, aliases: set[str], name: str) -> str:
    value = _optional_text(event, aliases)
    if not value:
        raise VirtualPaymentNotificationError(f"notification is missing {name}")
    return value


def _optional_text(event: object, aliases: set[str]) -> str:
    value = _find_value(event, aliases)
    return str(value).strip() if value not in (None, "") else ""


def _required_int(event: object, aliases: set[str], name: str) -> int:
    value = _optional_int(event, aliases)
    if value is None:
        raise VirtualPaymentNotificationError(f"notification is missing or has invalid {name}")
    return value


def _optional_int(event: object, aliases: set[str]) -> int | None:
    value = _find_value(event, aliases)
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise VirtualPaymentNotificationError("notification contains an invalid integer") from exc


def _find_value(event: object, aliases: set[str], *, recursive: bool = True) -> object | None:
    if isinstance(event, dict):
        for key, value in event.items():
            if _normalize_key(key) in aliases and value not in (None, ""):
                return value
        if recursive:
            for value in event.values():
                found = _find_value(_decode_nested_json(value), aliases)
                if found is not None:
                    return found
    elif recursive and isinstance(event, list):
        for value in event:
            found = _find_value(_decode_nested_json(value), aliases)
            if found is not None:
                return found
    return None


def _decode_nested_json(value: object) -> object:
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text.startswith(("{", "[")):
        return value
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return value


def _normalize_key(key: object) -> str:
    return "".join(character for character in str(key).lower() if character.isalnum())
