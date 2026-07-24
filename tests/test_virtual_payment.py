import hashlib
import hmac
import json

import pytest

from recordflow_agent.virtual_payment import (
    VirtualPaymentConfigurationError,
    VirtualPaymentNotificationSettings,
    VirtualPaymentNotificationError,
    VirtualPaymentSettings,
    build_payment_parameters,
    get_product,
    parse_payment_notification,
    validate_payment_notification,
)


def test_build_payment_parameters_uses_production_goods_contract():
    settings = VirtualPaymentSettings(
        appid="wx-test", offer_id="offer-1", appkey="production-key"
    )
    product = get_product(100)

    payment = build_payment_parameters(
        settings=settings,
        product=product,
        session_key="session-key",
        out_trade_no="order-1",
    )

    assert payment["mode"] == "short_series_goods"
    assert payment["env"] == 0
    assert payment["productId"] == "dot_100"
    assert payment["buyQuantity"] == 1
    assert payment["goodsPrice"] == 99
    assert payment["paySig"] == hmac.new(
        b"production-key",
        ("requestVirtualPayment&" + payment["signData"]).encode(),
        hashlib.sha256,
    ).hexdigest()
    assert payment["signature"] == hmac.new(
        b"session-key", payment["signData"].encode(), hashlib.sha256
    ).hexdigest()


def test_parse_payment_notification_accepts_nested_json_fields():
    event = {
        "Event": "xpay_goods_deliver_notify",
        "Env": 0,
        "OpenId": "openid-1",
        "OutTradeNo": "order-1",
        "GoodsInfo": json.dumps(
            {"ProductId": "dot_100", "GoodsNum": 1, "GoodsPrice": 99}
        ),
        "WeChatPayInfo": {"TransactionId": "wx-1", "OfferId": "offer-1"},
    }

    notification = parse_payment_notification(event)

    assert notification.out_trade_no == "order-1"
    assert notification.transaction_id == "wx-1"
    assert notification.product_id == "dot_100"
    assert notification.quantity == 1
    assert notification.amount_cents == 99


@pytest.mark.parametrize(
    "event",
    [
        {
            "Event": "xpay_goods_deliver_notify",
            "Env": 0,
            "OpenId": "openid-1",
            "OutTradeNo": "order-1",
        },
        {
            "Event": "xpay_goods_deliver_notify",
            "Env": 1,
            "OpenId": "openid-1",
            "OutTradeNo": "order-1",
            "TransactionId": "wx-1",
        },
    ],
)
def test_parse_payment_notification_rejects_incomplete_or_sandbox_events(event):
    with pytest.raises(VirtualPaymentNotificationError):
        parse_payment_notification(event)


def test_parse_payment_notification_ignores_unrelated_message():
    assert parse_payment_notification({"Event": "user_enter_tempsession"}) is None


def test_payment_notification_must_match_stored_user():
    notification = parse_payment_notification(
        {
            "Event": "xpay_goods_deliver_notify",
            "Env": 0,
            "OpenId": "openid-other",
            "OutTradeNo": "order-1",
            "TransactionId": "wx-1",
            "ProductId": "dot_500",
        }
    )
    settings = VirtualPaymentNotificationSettings(
        appid="wx-test", offer_id="offer-1", token="token", aes_key="A" * 43
    )

    with pytest.raises(VirtualPaymentNotificationError, match="user"):
        validate_payment_notification(
            notification,
            order={
                "provider": "wechat_virtual",
                "environment": 0,
                "offer_id": "offer-1",
                "product_id": "dot_100",
                "points": 100,
                "amount_cents": 99,
            },
            settings=settings,
            expected_openid="openid-1",
        )


def test_payment_notification_must_match_stored_product():
    notification = parse_payment_notification(
        {
            "Event": "xpay_goods_deliver_notify",
            "Env": 0,
            "OpenId": "openid-1",
            "OutTradeNo": "order-1",
            "TransactionId": "wx-1",
            "ProductId": "dot_500",
        }
    )
    settings = VirtualPaymentNotificationSettings(
        appid="wx-test", offer_id="offer-1", token="token", aes_key="A" * 43
    )

    with pytest.raises(VirtualPaymentNotificationError, match="product"):
        validate_payment_notification(
            notification,
            order={
                "provider": "wechat_virtual",
                "environment": 0,
                "offer_id": "offer-1",
                "product_id": "dot_100",
                "points": 100,
                "amount_cents": 99,
            },
            settings=settings,
            expected_openid="openid-1",
        )


def test_payment_settings_reject_non_goods_mode(monkeypatch):
    monkeypatch.setenv("WECHAT_VIRTUAL_MODE", "short_series_coin")

    with pytest.raises(VirtualPaymentConfigurationError):
        VirtualPaymentSettings.from_env()
